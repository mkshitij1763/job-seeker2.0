import json

import respx

from jobseeker.contacts.people import Candidate
from jobseeker.contacts.providers import ApifyClient, HunterClient

SEARCH = "https://api.apify.com/v2/acts/harvestapi~linkedin-profile-search/run-sync-get-dataset-items"
PROFILE = "https://api.apify.com/v2/acts/harvestapi~linkedin-profile-scraper/run-sync-get-dataset-items"


@respx.mock
def test_apify_search_people():
    route = respx.post(SEARCH).respond(json=[
        {"firstName": "Asha", "lastName": "Rao", "headline": "Product Lead at Zepto",
         "linkedinUrl": "https://www.linkedin.com/in/asharao/"},
        {"firstName": "", "lastName": "", "linkedinUrl": "https://www.linkedin.com/in/x"}])
    out = ApifyClient("tok").search_people("Zepto", "product manager", "Bengaluru")
    assert out == [Candidate("Asha Rao", "Product Lead at Zepto", "https://www.linkedin.com/in/asharao")]
    req = route.calls[0].request
    body = json.loads(req.content)
    assert body["currentCompanies"] == ["Zepto"] and body["profileScraperMode"] == "Short" and body["takePages"] == 1
    assert req.url.params["token"] == "tok"


@respx.mock
def test_apify_profile_email():
    route = respx.post(PROFILE).respond(json=[{"emails": [{"email": "asha@zepto.com", "status": "valid"}]}])
    assert ApifyClient("tok").profile_email("https://www.linkedin.com/in/asharao") == "asha@zepto.com"
    body = json.loads(route.calls[0].request.content)
    assert body == {"profileScraperMode": "Profile details + email search ($10 per 1k)",
                    "queries": ["https://www.linkedin.com/in/asharao"]}


@respx.mock
def test_apify_profile_without_email():
    respx.post(PROFILE).respond(json=[{"emails": []}])
    assert ApifyClient("tok").profile_email("https://www.linkedin.com/in/x") is None


@respx.mock
def test_hunter_domain_search():
    route = respx.get("https://api.hunter.io/v2/domain-search").respond(json={"data": {
        "pattern": "{first}.{last}",
        "emails": [{"value": "priya.nair@zepto.com", "first_name": "Priya", "last_name": "Nair"}]}})
    out = HunterClient("hk").domain_search("zepto.com")
    assert out == {"pattern": "first.last", "emails": [("Priya", "Nair", "priya.nair@zepto.com")]}
    assert route.calls[0].request.url.params["domain"] == "zepto.com"
