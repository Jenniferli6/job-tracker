#!/usr/bin/env python3
"""
Fills in "custom" ATS entries (with careers page URLs) for known Big Tech /
enterprise companies that merge_discovered.py left as "TODO" — companies
that aren't on Greenhouse/Lever/Ashby at all.

Run this AFTER merge_discovered.py, in the same job-tracker folder:
    python apply_custom_urls.py

It only touches entries currently marked "ats": "TODO" and whose name is in
the URLS dict below — any TODO not covered here is left alone for you to
handle manually.

NOTE: these URLs are best-effort from general knowledge, not verified live.
Spot-check a few before relying on them long-term — company career sites
get restructured periodically.
"""

import json
from pathlib import Path

COMPANIES_FILE = Path("companies.json")

URLS = {
    "Google / Alphabet": "https://www.google.com/about/careers/applications/jobs/results",
    "Microsoft": "https://jobs.careers.microsoft.com/global/en/search",
    "Amazon / AWS": "https://www.amazon.jobs/en/",
    "Meta": "https://www.metacareers.com/jobs",
    "Apple": "https://jobs.apple.com/en-us/search",
    "NVIDIA": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    "Tesla": "https://www.tesla.com/careers/search",
    "Netflix": "https://explore.jobs.netflix.net/careers",
    "Uber": "https://www.uber.com/us/en/careers/list/",
    "ByteDance / TikTok": "https://careers.tiktok.com/position",
    "DoorDash": "https://careers.doordash.com/",
    "Snap": "https://careers.snap.com/jobs",
    "Shopify": "https://www.shopify.com/careers",
    "Booking Holdings": "https://careers.bookingholdings.com/",
    "Expedia Group": "https://careers.expediagroup.com/",
    "MercadoLibre": "https://careers.mercadolibre.com/",
    "Alibaba": "https://careers.alibabagroup.com/",
    "Tencent": "https://careers.tencent.com/",
    "Sea Limited": "https://www.sea.com/careers",
    "Google DeepMind": "https://deepmind.google/about/careers/",
    "Microsoft AI": "https://jobs.careers.microsoft.com/global/en/search",
    "Meta AI": "https://www.metacareers.com/jobs",
    "Hugging Face": "https://apply.workable.com/huggingface/",
    "Glean": "https://www.glean.com/careers",
    "Groq": "https://groq.com/careers/",
    "Replicate": "https://replicate.com/about",
    "Weights & Biases": "https://wandb.ai/site/careers",
    "dbt Labs": "https://www.getdbt.com/careers",
    "GitHub": "https://github.careers/",
    "HashiCorp": "https://www.hashicorp.com/careers",
    "DigitalOcean": "https://www.digitalocean.com/careers",
    "Akamai": "https://www.akamai.com/careers",
    "Cloudera": "https://www.cloudera.com/careers.html",
    "Salesforce": "https://www.salesforce.com/company/careers/",
    "ServiceNow": "https://careers.servicenow.com/",
    "Adobe": "https://careers.adobe.com/",
    "Oracle": "https://www.oracle.com/careers/",
    "SAP": "https://jobs.sap.com/",
    "IBM": "https://www.ibm.com/careers",
    "Cisco": "https://jobs.cisco.com/",
    "Workday": "https://workday.wd5.myworkdayjobs.com/Workday",
    "Atlassian": "https://www.atlassian.com/company/careers/all-jobs",
    "Zoom": "https://careers.zoom.us/jobs/search",
    "Slack": "https://www.metacareers.com/jobs",
    "monday.com": "https://monday.com/careers/positions",
    "Box": "https://www.box.com/careers",
    "DocuSign": "https://careers.docusign.com/",
    "Canva": "https://www.canva.com/careers/jobs/",
    "Intuit": "https://jobs.intuit.com/",
    "Autodesk": "https://autodesk.wd1.myworkdayjobs.com/Ext",
    "Procore": "https://www.procore.com/jobs",
    "Zendesk": "https://www.zendesk.com/careers/",
    "PayPal": "https://careers.pypl.com/",
    "Klarna": "https://www.klarna.com/careers/",
    "Wise": "https://wise.jobs/",
    "Rippling": "https://www.rippling.com/careers",
    "BILL": "https://careers.bill.com/",
    "Revolut": "https://www.revolut.com/careers/",
    "Checkout.com": "https://www.checkout.com/careers",
    "Circle": "https://www.circle.com/careers",
    "Chainalysis": "https://www.chainalysis.com/careers/",
    "AMD": "https://careers.amd.com/",
    "Intel": "https://jobs.intel.com/",
    "Broadcom": "https://careers.broadcom.com/",
    "Qualcomm": "https://careers.qualcomm.com/",
    "TSMC": "https://careers.tsmc.com/",
    "ASML": "https://www.asml.com/en/careers",
    "Arm": "https://careers.arm.com/",
    "Micron": "https://careers.micron.com/",
    "Applied Materials": "https://careers.appliedmaterials.com/",
    "Lam Research": "https://www.lamresearch.com/careers/",
    "Marvell": "https://careers.marvell.com/",
    "Texas Instruments": "https://careers.ti.com/",
    "Samsung Electronics": "https://www.samsung.com/us/careers/",
    "SK Hynix": "https://careers.skhynix.com/",
    "Palo Alto Networks": "https://jobs.paloaltonetworks.com/",
    "CrowdStrike": "https://www.crowdstrike.com/careers/",
    "SentinelOne": "https://www.sentinelone.com/careers/",
    "Fortinet": "https://www.fortinet.com/corporate/careers/",
    "CyberArk": "https://www.cyberark.com/careers/",
    "Anduril": "https://www.anduril.com/careers/",
    "Cruise": "https://www.getcruise.com/careers",
    "Rivian": "https://rivian.com/careers/search",
    "Boston Dynamics": "https://bostondynamics.com/careers/",
    "Zipline": "https://www.flyzipline.com/careers",
}


def main():
    data = json.loads(COMPANIES_FILE.read_text())
    updated = 0
    for entry in data:
        if entry.get("ats") == "TODO" and entry["name"] in URLS:
            entry["ats"] = "custom"
            entry["url"] = URLS[entry["name"]]
            entry.pop("notes", None)
            updated += 1

    COMPANIES_FILE.write_text(json.dumps(data, indent=2))
    still_todo = [e["name"] for e in data if e.get("ats") == "TODO"]
    print(f"Filled in {updated} custom entries.")
    print(f"Still TODO ({len(still_todo)}): {still_todo}")


if __name__ == "__main__":
    main()
