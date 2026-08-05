#!/usr/bin/env python3
"""
Job application automation (local only — not run in GitHub Actions).

Works through the dashboard's job list (jobs_log.json + roles_snapshot.json,
same files docs/index.html reads) in batches, newest first, skipping
anything already recorded in application_status.json. For each Greenhouse /
Lever / Ashby posting it drives a real visible browser (Playwright), attaches
the resume, and fills whatever fields it can map from applicant_profile.json.

Anything it can't map (a required field with no match) pauses and asks in
the terminal, then remembers the answer in applicant_profile.json's
learned_answers for next time. Salary/comp questions always pause fresh —
there's no fixed default for those.

It stops short of clicking Submit. You review the filled form in the
browser, then answer the terminal prompt to record what actually happened.

Setup:
    pip install playwright
    playwright install chromium

Run:
    python apply.py [--batch 30]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

JOBS_LOG_FILE = Path("jobs_log.json")
ROLES_SNAPSHOT_FILE = Path("roles_snapshot.json")
STATUS_FILE = Path("application_status.json")
DOCS_STATUS_FILE = Path("docs/application_status.json")
PROFILE_FILE = Path("applicant_profile.json")

DEFAULT_BATCH = 30

FIELD_KEYWORDS = [
    (["first name"], "first_name"),
    (["last name", "surname"], "last_name"),
    (["full name"], "full_name"),
    (["email"], "email"),
    (["phone", "mobile"], "phone"),
    (["linkedin"], "linkedin_url"),
    (["github", "portfolio", "personal website"], "github_url"),
    (["work authorization", "sponsorship", "require visa", "legally authorized"], "work_authorization"),
    (["current location", "location", "city", "based"], "location"),
    (["gender", "race", "ethnicity", "veteran", "disability", "eeo", "self-identif"], "eeo_response"),
    (["salary", "compensation expectation", "pay expectation", "desired salary"], "salary_expectation"),
]

DECLINE_KEYWORDS = ["decline", "prefer not", "don't wish", "do not wish", "not disclose"]


# ---------- Queue building ----------

def detect_platform(url):
    host = urlparse(url).netloc.lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    return None


def is_custom_alert(title):
    return "Careers page content changed" in (title or "")


def build_queue(status):
    combined = {}

    if JOBS_LOG_FILE.exists():
        for j in json.loads(JOBS_LOG_FILE.read_text()):
            url = j.get("url")
            if not url or is_custom_alert(j.get("title", "")):
                continue
            platform = detect_platform(url)
            if not platform:
                continue
            combined[url] = {
                "url": url,
                "company": j.get("company", ""),
                "title": j.get("title", ""),
                "location": j.get("location", ""),
                "platform": platform,
                "date": j.get("date_found", ""),
            }

    if ROLES_SNAPSHOT_FILE.exists():
        snapshot = json.loads(ROLES_SNAPSHOT_FILE.read_text())
        scanned_date = (snapshot.get("scanned_at") or "")[:10]
        for r in snapshot.get("roles", []):
            url = r.get("url")
            if not url:
                continue
            platform = detect_platform(url)
            if not platform:
                continue
            if url in combined:
                continue  # jobs_log entry already has a more precise date
            combined[url] = {
                "url": url,
                "company": r.get("company", ""),
                "title": r.get("title", ""),
                "location": r.get("location", ""),
                "platform": platform,
                "date": scanned_date,
            }

    queue = [e for e in combined.values() if e["url"] not in status]
    queue.sort(key=lambda e: e.get("date") or "", reverse=True)
    return queue


# ---------- Profile / status persistence ----------

def load_profile():
    if not PROFILE_FILE.exists():
        sys.exit(f"{PROFILE_FILE} not found — create it with your application info first.")
    return json.loads(PROFILE_FILE.read_text())


def save_profile(profile):
    PROFILE_FILE.write_text(json.dumps(profile, indent=2))


def load_status():
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text())
    return {}


def save_status(status):
    text = json.dumps(status, indent=2, sort_keys=True)
    STATUS_FILE.write_text(text)
    DOCS_STATUS_FILE.parent.mkdir(exist_ok=True)
    DOCS_STATUS_FILE.write_text(text)


# ---------- Form field matching ----------

REQUIRED_MARKERS = "*✱★✻＊"  # ATS forms use various glyphs for "required"


def normalize_question(text):
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"\(required\)", "", t, flags=re.I).strip()
    t = t.rstrip(REQUIRED_MARKERS).strip()
    return t.lower()


def match_field(label_text):
    l = label_text.lower()
    for keywords, key in FIELD_KEYWORDS:
        if any(k in l for k in keywords):
            return key
    if l.strip() in ("name", "your name"):
        return "full_name"
    return None


def is_field_required(label_text, input_el):
    try:
        if input_el.get_attribute("required") is not None:
            return True
        if (input_el.get_attribute("aria-required") or "").lower() == "true":
            return True
    except Exception:
        pass
    t = label_text.strip()
    return (t and t[-1] in REQUIRED_MARKERS) or "required" in t.lower()


def prompt_for_value(label_text):
    print(f'  New question: "{label_text}"')
    answer = input("  Your answer (leave blank to skip this job): ").strip()
    return answer or None


# ---------- Playwright helpers ----------

def has_form_fields(root):
    try:
        return root.locator("input:not([type=hidden]), select, textarea").count() > 0
    except Exception:
        return False


def get_form_root(page, platform):
    if platform != "greenhouse":
        return page
    # Most job-boards.greenhouse.io postings render the form directly on the
    # page — only look inside an iframe (the embedded-on-a-company-site case)
    # if the top-level page genuinely has no fields of its own. Blindly
    # preferring any iframe[src*='greenhouse.io'] can grab an unrelated
    # widget/analytics iframe and leave the real form untouched.
    if has_form_fields(page):
        return page
    try:
        iframe_selector = "iframe[id^='grnhse_iframe'], iframe[src*='greenhouse.io']"
        if page.locator(iframe_selector).count() > 0:
            frame_root = page.frame_locator(iframe_selector).first
            if has_form_fields(frame_root):
                return frame_root
    except Exception:
        pass
    return page


def click_apply_if_present(page):
    for role in ("link", "button"):
        for name in ("Apply for this job", "Apply for this Job", "Apply Now", "Apply"):
            try:
                loc = page.get_by_role(role, name=name, exact=False)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    page.wait_for_timeout(800)
                    return
            except Exception:
                pass


def wait_for_form(page, root):
    """The application form is usually client-rendered after navigation —
    wait for a real field to mount instead of scanning too early."""
    try:
        root.locator("input:not([type=hidden]), select, textarea").first.wait_for(
            state="visible", timeout=15000
        )
    except Exception:
        pass
    page.wait_for_timeout(1000)  # let late-hydrating fields (custom questions) settle too


def clean_label_text(locator):
    """Read a label/legend/heading's own text, excluding any nested form
    control's content (e.g. a <select>'s option list) — some ATS markup
    wraps the control inside its label, and plain inner_text() would
    otherwise pull in every <option>."""
    try:
        text = locator.evaluate(
            """el => {
                const clone = el.cloneNode(true);
                clone.querySelectorAll('select, input, textarea, option').forEach(n => n.remove());
                return clone.textContent.replace(/\\s+/g, ' ').trim();
            }"""
        )
        if text:
            return text
    except Exception:
        pass
    try:
        return locator.inner_text().strip()
    except Exception:
        return ""


def get_label_text(root, input_el):
    """Try several strategies since ATS forms don't consistently use <label for>."""
    try:
        aria = input_el.get_attribute("aria-label")
        if aria and aria.strip():
            return aria.strip()
    except Exception:
        pass
    try:
        labelledby = input_el.get_attribute("aria-labelledby")
        if labelledby:
            texts = []
            for ref_id in labelledby.split():
                el = root.locator(f'[id="{ref_id}"]')
                if el.count() > 0:
                    texts.append(clean_label_text(el.first))
            if any(texts):
                return " ".join(t for t in texts if t)
    except Exception:
        pass
    try:
        input_id = input_el.get_attribute("id")
        if input_id:
            lbl = root.locator(f'label[for="{input_id}"]')
            if lbl.count() > 0:
                return clean_label_text(lbl.first)
    except Exception:
        pass
    try:
        ancestor_label = input_el.locator("xpath=ancestor::label[1]")
        if ancestor_label.count() > 0:
            return clean_label_text(ancestor_label.first)
    except Exception:
        pass
    try:
        container_label = input_el.locator(
            "xpath=ancestor::*[self::div or self::fieldset][position()<=4]//label"
        )
        if container_label.count() > 0:
            return clean_label_text(container_label.first)
    except Exception:
        pass
    try:
        placeholder = input_el.get_attribute("placeholder")
        if placeholder and placeholder.strip():
            return placeholder.strip()
    except Exception:
        pass
    return ""


def get_group_question(first_input):
    try:
        legend = first_input.locator("xpath=ancestor::fieldset[1]/legend")
        if legend.count() > 0:
            return clean_label_text(legend.first)
    except Exception:
        pass
    try:
        container = first_input.locator("xpath=ancestor::fieldset[1]")
        if container.count() == 0:
            container = first_input.locator("xpath=ancestor::*[self::div][position()<=3]")
        heading = container.locator("label, h1, h2, h3, h4, legend").first
        if heading.count() > 0:
            return clean_label_text(heading)
    except Exception:
        pass
    return ""


def is_filled(input_el):
    try:
        type_attr = (input_el.get_attribute("type") or "").lower()
    except Exception:
        type_attr = ""
    if type_attr in ("radio", "checkbox"):
        try:
            return input_el.is_checked()
        except Exception:
            return False
    try:
        val = input_el.input_value()
        return bool(val and val.strip())
    except Exception:
        return False


def set_field_value(input_el, value, profile=None):
    try:
        tag = input_el.evaluate("el => el.tagName.toLowerCase()")
    except Exception:
        tag = ""
    try:
        type_attr = (input_el.get_attribute("type") or "").lower()
    except Exception:
        type_attr = ""

    if tag == "select":
        # try the mapped value, then (for country-only pickers where a
        # city/state string like "Durham, NC" won't match any option) a
        # dedicated country fallback from the profile
        for candidate in (value, (profile or {}).get("country")):
            if not candidate:
                continue
            try:
                input_el.select_option(label=str(candidate))
                return
            except Exception:
                pass
            try:
                input_el.select_option(value=str(candidate))
                return
            except Exception:
                pass
        raise ValueError(f'no matching <select> option for "{value}"')

    if type_attr in ("radio", "checkbox"):
        input_el.check()
        return
    if type_attr == "file":
        input_el.set_input_files(str(value))
        return
    input_el.fill(str(value))


def fill_single_field(input_el, label_text, profile):
    """Returns True if handled (filled, skipped-as-optional, or matched), False
    if the user chose to skip the whole job at a required-field prompt."""
    key = match_field(label_text)

    if key == "salary_expectation":
        if not is_field_required(label_text, input_el):
            return True
        value = prompt_for_value(label_text)
        if value is None:
            return False
        try:
            set_field_value(input_el, value, profile)
        except Exception as e:
            print(f'  could not fill "{label_text}": {e}')
        return True

    value = profile.get(key) if key else None
    if not value:
        value = profile.get("learned_answers", {}).get(normalize_question(label_text))
    if not value:
        if not is_field_required(label_text, input_el):
            return True
        value = prompt_for_value(label_text)
        if value is None:
            return False
        profile.setdefault("learned_answers", {})[normalize_question(label_text)] = value
        save_profile(profile)

    try:
        set_field_value(input_el, value, profile)
    except Exception as e:
        print(f'  could not fill "{label_text}": {e}')
    return True


def fill_text_like_fields(root, profile):
    filled_count = 0
    fields = root.locator(
        "input:not([type=hidden]):not([type=file]):not([type=radio])"
        ":not([type=checkbox]):not([type=submit]):not([type=button]), select, textarea"
    )
    try:
        count = fields.count()
    except Exception:
        count = 0

    for i in range(count):
        input_el = fields.nth(i)
        try:
            if not input_el.is_visible() or is_filled(input_el):
                continue
        except Exception:
            continue

        label_text = get_label_text(root, input_el)
        if not label_text:
            continue

        if not fill_single_field(input_el, label_text, profile):
            return filled_count, False
        filled_count += 1

    return filled_count, True


def fill_radio_checkbox_groups(root, profile):
    inputs = root.locator("input[type=radio], input[type=checkbox]")
    try:
        count = inputs.count()
    except Exception:
        count = 0

    groups = {}  # name -> list of input elements, in DOM order
    for i in range(count):
        el = inputs.nth(i)
        try:
            if not el.is_visible():
                continue
        except Exception:
            continue
        name = None
        try:
            name = el.get_attribute("name")
        except Exception:
            pass
        key = name or f"__group_{i}"
        groups.setdefault(key, []).append(el)

    filled_count = 0
    for options in groups.values():
        if any(is_filled(o) for o in options):
            continue  # already answered (e.g. a default was pre-checked)

        option_texts = [get_label_text(root, o) for o in options]

        # EEO/voluntary decline options are recognizable by wording alone —
        # handle regardless of whether the group's question text was found.
        declined = False
        for opt, text in zip(options, option_texts):
            if any(k in text.lower() for k in DECLINE_KEYWORDS):
                try:
                    opt.click()
                    filled_count += 1
                except Exception:
                    pass
                declined = True
                break
        if declined:
            continue

        question = get_group_question(options[0])
        if not question:
            continue
        key = match_field(question)
        if key in (None, "eeo_response"):
            continue  # no confident match and not a recognized decline case

        value = profile.get(key) or profile.get("learned_answers", {}).get(
            normalize_question(question)
        )
        if not value:
            if not is_field_required(question, options[0]):
                continue
            value = prompt_for_value(question)
            if value is None:
                return filled_count, False
            profile.setdefault("learned_answers", {})[normalize_question(question)] = value
            save_profile(profile)

        for opt, text in zip(options, option_texts):
            if value.lower() in text.lower() or text.lower() in value.lower():
                try:
                    opt.click()
                    filled_count += 1
                except Exception:
                    pass
                break

    return filled_count, True


def fill_form(page, root, profile):
    """Returns False if the user chose to skip this job at a required prompt."""
    file_inputs = root.locator("input[type=file]")
    try:
        n = file_inputs.count()
    except Exception:
        n = 0
    for i in range(n):
        try:
            file_inputs.nth(i).set_input_files(profile["resume_path"])
        except Exception:
            pass
    if n:
        page.wait_for_timeout(1500)  # some ATSes auto-populate fields after resume parsing

    text_count, ok = fill_text_like_fields(root, profile)
    if not ok:
        return False

    radio_count, ok = fill_radio_checkbox_groups(root, profile)
    if not ok:
        return False

    if text_count == 0 and radio_count == 0 and n == 0:
        print("  Warning: nothing matched on this form — check it manually before continuing.")

    return True


def process_job(page, job, profile):
    print(f"\n=== {job['company']} — {job['title']} ({job['platform']}) ===")
    print(job["url"])
    try:
        page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"  navigation failed: {e}")
        return "pending_new_info"

    click_apply_if_present(page)
    root = get_form_root(page, job["platform"])
    wait_for_form(page, root)

    completed = fill_form(page, root, profile)
    if not completed:
        return "pending_new_info"

    print("  Filled. Review the form in the browser.")
    while True:
        choice = input(
            "  [Enter]=submitted  s=filled only  p=pending  x=skip  q=quit batch: "
        ).strip().lower()
        if choice == "":
            return "submitted"
        if choice == "s":
            return "info_filled"
        if choice == "p":
            return "pending_new_info"
        if choice == "x":
            return "skipped"
        if choice == "q":
            return "QUIT"
        print("  not understood, try again")


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--url", help="Process one specific job URL instead of pulling a batch from the queue")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright not installed — run: pip install playwright && playwright install chromium")

    profile = load_profile()
    status = load_status()

    if args.url:
        platform = detect_platform(args.url)
        if not platform:
            sys.exit("That URL doesn't look like a Greenhouse, Lever, or Ashby posting.")
        match = next((j for j in build_queue(status) if j["url"] == args.url), None)
        queue = [match] if match else [{
            "url": args.url, "company": "", "title": "", "platform": platform, "date": "",
        }]
    else:
        queue = build_queue(status)[:args.batch]

    if not queue:
        print("Nothing to do — queue is empty or everything's already been processed.")
        return

    print(f"{len(queue)} job(s) queued this run.")

    counts = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_context().new_page()

        for job in queue:
            result = process_job(page, job, profile)
            if result == "QUIT":
                print("Stopping batch.")
                break
            status[job["url"]] = {
                "company": job["company"],
                "title": job["title"],
                "status": result,
                "date": datetime.date.today().isoformat(),
            }
            save_status(status)
            counts[result] = counts.get(result, 0) + 1

        browser.close()

    print("\nBatch summary:")
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
