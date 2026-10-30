"""Generate the "Lead Capture + CRM" n8n workflow (mock data, no credentials)."""
import json
import uuid

nodes = []
connections = {}
pin = {}


def nid():
    return str(uuid.uuid4())


def node(name, type_, version, pos, params, mock=None, **extra):
    n = {"id": nid(), "name": name, "type": type_, "typeVersion": version,
         "position": list(pos), "parameters": params}
    n.update(extra)
    nodes.append(n)
    if mock is not None:
        pin[name] = [{"json": m} for m in mock]
    return n


def link(src, dst, out=0):
    outs = connections.setdefault(src, {"main": []})["main"]
    while len(outs) <= out:
        outs.append([])
    outs[out].append({"node": dst, "type": "main", "index": 0})


def cond(left, op_type, operation, right=None):
    c = {"id": nid(), "leftValue": left,
         "operator": {"type": op_type, "operation": operation}}
    if right is None:
        c["rightValue"] = ""
        c["operator"]["singleValue"] = True
    else:
        c["rightValue"] = right
    return c


def conditions(*cs):
    return {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": list(cs), "combinator": "and"}


def switch_rules(rules):
    return {"rules": {"values": [
        {"conditions": conditions(c), "renameOutput": True, "outputKey": key} for key, c in rules
    ]}, "options": {}}


def sheet(name, pos, tab, mock):
    return node(name, "n8n-nodes-base.googleSheets", 4.7, pos, {
        "operation": "append",
        "documentId": {"__rl": True, "mode": "id", "value": "1MOCK-leads-sheet-id"},
        "sheetName": {"__rl": True, "mode": "name", "value": tab},
        "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": [], "schema": []},
        "options": {},
    }, mock)


def http(name, pos, url, body, mock, method="POST"):
    return node(name, "n8n-nodes-base.httpRequest", 4.5, pos, {
        "method": method, "url": url,
        "sendBody": True, "specifyBody": "json", "jsonBody": body, "options": {},
    }, mock)


LEAD = {
    "name": "Alex Chen", "email": "alex.chen@acme-corp.com", "phone": "+1 415 555 0142",
    "company": "Acme Corp", "budget": 30000, "source": "web_form",
    "message": "We need to automate lead routing for 3 sales teams, ~2k leads/month. Looking to start next month.",
}

# ---------- Capture & Normalize ----------
node("Form Lead In", "n8n-nodes-base.webhook", 2.1, (0, 300), {
    "httpMethod": "POST", "path": "lead-in", "options": {},
}, [{"headers": {"content-type": "application/json"}, "params": {}, "query": {}, "body": LEAD}],
    webhookId=nid())

node("Scoring Rules (edit here)", "n8n-nodes-base.set", 3.5, (220, 300), {
    "assignments": {"assignments": [
        {"id": nid(), "name": "hotThreshold", "value": 80, "type": "number"},
        {"id": nid(), "name": "warmThreshold", "value": 50, "type": "number"},
        {"id": nid(), "name": "corpEmailFloor", "value": 50, "type": "number"},
        {"id": nid(), "name": "budgetFloor", "value": 10000, "type": "number"},
        {"id": nid(), "name": "longMessageChars", "value": 80, "type": "number"},
    ]},
    "includeOtherFields": True, "options": {},
})

node("Normalize (Web)", "n8n-nodes-base.set", 3.5, (440, 300), {
    "assignments": {"assignments": [
        {"id": nid(), "name": "name", "value": "={{ ($json.body.name || '').trim() }}", "type": "string"},
        {"id": nid(), "name": "email", "value": "={{ ($json.body.email || '').trim().toLowerCase() }}", "type": "string"},
        {"id": nid(), "name": "phone", "value": "={{ ($json.body.phone || '').trim() }}", "type": "string"},
        {"id": nid(), "name": "company", "value": "={{ $json.body.company }}", "type": "string"},
        {"id": nid(), "name": "budget", "value": "={{ Number($json.body.budget) || 0 }}", "type": "number"},
        {"id": nid(), "name": "message", "value": "={{ $json.body.message }}", "type": "string"},
        {"id": nid(), "name": "source", "value": "={{ $json.body.source || 'web_form' }}", "type": "string"},
    ]},
    "options": {},
})

node("Validate Lead", "n8n-nodes-base.switch", 3.4, (660, 300), switch_rules([
    ("Missing Email", cond("={{ $json.email }}", "string", "empty")),
    ("Missing Name", cond("={{ $json.name }}", "string", "empty")),
    ("Valid Lead", cond("={{ $json.email }}", "string", "notEmpty")),
]))

sheet("Log Incomplete Lead", (900, 100), "Incomplete",
      [{"row_number": 12, "name": "Alex Chen", "email": "", "reason": "missing_email"}])

node("Ask for Details", "n8n-nodes-base.gmail", 2.2, (900, 300), {
    "sendTo": "={{ $json.email }}",
    "subject": "Quick question about your request",
    "emailType": "text",
    "message": "Hi there,\n\nThanks for reaching out! Could you reply with your name so we can route you to the right person?\n\nBest,\nSales Team",
    "options": {},
}, [{"id": "18c2f0mock01", "threadId": "18c2f0mock01", "labelIds": ["SENT"]}])

# ---------- Validate & Dedup ----------
node("Search by Email", "n8n-nodes-base.hubspot", 2.2, (900, 500), {
    "authentication": "appToken",
    "operation": "search",
    "filterGroupsUi": {"filterGroupsValues": [{"filtersUi": {"filterValues": [
        {"propertyName": "email|string", "value": "={{ $json.email }}"},
    ]}}]},
    "additionalFields": {},
}, [{"id": "", "total": 0}])

node("Is Duplicate?", "n8n-nodes-base.if", 2.3, (1120, 500), {
    "conditions": conditions(cond("={{ $json.recentSubmission }}", "boolean", "true")),
    "options": {},
})

sheet("Log Duplicate Lead", (1340, 320), "Duplicates",
      [{"row_number": 48, "email": "alex.chen@acme-corp.com", "reason": "duplicate_submission"}])

# ---------- AI + Rules Score ----------
node("Score Lead (LLM)", "@n8n/n8n-nodes-langchain.openAi", 1.8, (1340, 500), {
    "modelId": {"__rl": True, "mode": "list", "value": "gpt-4o", "cachedResultName": "GPT-4O"},
    "messages": {"values": [
        {"role": "system", "content": "You are a B2B lead qualification assistant. Return JSON: {score (0-100), tier (hot|warm|cold), reason, message}."},
        {"content": "=Name: {{ $('Normalize (Web)').item.json.name }}\nEmail: {{ $('Normalize (Web)').item.json.email }}\nCompany: {{ $('Normalize (Web)').item.json.company }}\nBudget: {{ $('Normalize (Web)').item.json.budget }}\nMessage: {{ $('Normalize (Web)').item.json.message }}"},
    ]},
    "jsonOutput": True,
    "options": {"temperature": 0.2},
}, [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": {
    "score": 86, "tier": "hot",
    "reason": "Corporate domain, clear budget ($30k), concrete use case and timeline.",
    "message": "Hi Alex, thanks for reaching out about automating lead routing for your sales teams...",
}}}])

node("Parse Score", "n8n-nodes-base.code", 2, (1560, 500), {"jsCode": """// Try/catch fallback: warm / 50+
const lead = $('Normalize (Web)').item.json;
let ai;
try {
  ai = $json.message.content;
  if (typeof ai === 'string') ai = JSON.parse(ai);
} catch (e) {
  ai = { score: 50, tier: 'warm', reason: 'LLM parse failed - fallback', message: '' };
}
return [{ json: { ...lead, score: Number(ai.score) || 50, reason: ai.reason, aiMessage: ai.message } }];"""})

node("Apply Rules Floor", "n8n-nodes-base.code", 2, (1780, 500), {"jsCode": """// Floor rule: corp email + budget + long msg
const rules = $('Scoring Rules (edit here)').item.json;
const lead = $json;
const freeMail = /@(gmail|yahoo|hotmail|outlook|qq|163)\\./i.test(lead.email);
let score = lead.score;
if (!freeMail && lead.budget >= rules.budgetFloor && (lead.message || '').length >= rules.longMessageChars) {
  score = Math.max(score, rules.corpEmailFloor);
}
const tier = score >= rules.hotThreshold ? 'hot' : score >= rules.warmThreshold ? 'warm' : 'cold';
return [{ json: { ...lead, score, tier } }];"""})

# ---------- CRM + Outreach + Notify ----------
node("Is New Contact?", "n8n-nodes-base.if", 2.3, (2000, 500), {
    "conditions": conditions(cond("={{ $('Search by Email').item.json.total }}", "number", "equals", 0)),
    "options": {},
})

http("Create Contact", (2240, 340), "https://api.hubapi.com/crm/v3/objects/contacts",
     "={\n  \"properties\": {\n    \"email\": \"{{ $json.email }}\",\n    \"firstname\": \"{{ $json.name }}\",\n    \"phone\": \"{{ $json.phone }}\",\n    \"company\": \"{{ $json.company }}\",\n    \"hs_lead_status\": \"NEW\",\n    \"lead_score\": {{ $json.score }}\n  }\n}",
     [{"id": "90210001", "properties": {"email": "alex.chen@acme-corp.com", "lead_score": "86"}, "tier": "hot"}])

node("Is Auto Followup?", "n8n-nodes-base.if", 2.3, (2240, 700), {
    "conditions": conditions(cond("={{ $('Search by Email').item.json.properties?.lifecyclestage }}", "string", "equals", "lead")),
    "options": {},
})

http("Update Contact", (2460, 540), "=https://api.hubapi.com/crm/v3/objects/contacts/{{ $('Search by Email').item.json.id }}",
     "={\n  \"properties\": {\n    \"lead_score\": {{ $json.score }},\n    \"hs_lead_status\": \"OPEN\"\n  }\n}",
     [{"id": "90210001", "updatedAt": "2026-10-30T08:00:00Z", "tier": "warm"}], method="PATCH")

node("Prepare Update Diff", "n8n-nodes-base.code", 2, (2460, 820), {"jsCode": """const prev = $('Search by Email').item.json.properties || {};
const lead = $json;
const diff = ['phone', 'company'].filter(k => prev[k] && prev[k] !== lead[k])
  .map(k => `${k}: ${prev[k]} → ${lead[k]}`);
return [{ json: { ...lead, diff: diff.join('\\n') || 'no field changes' } }];"""})

http("Notify Sales of Update", (2700, 820), "https://slack.com/api/chat.postMessage",
     "={\n  \"channel\": \"#leads-updates\",\n  \"text\": \"Existing contact {{ $json.email }} resubmitted:\\n{{ $json.diff }}\"\n}",
     [{"ok": True, "channel": "C0MOCKUPD", "ts": "1793347200.000100"}])

node("Tier Router", "n8n-nodes-base.switch", 3.4, (2700, 440), switch_rules([
    ("hot", cond("={{ $json.tier }}", "string", "equals", "hot")),
    ("warm", cond("={{ $json.tier }}", "string", "equals", "warm")),
    ("cold", cond("={{ $json.tier }}", "string", "equals", "cold")),
]))

node("First-Touch Email", "n8n-nodes-base.gmail", 2.2, (3000, 180), {
    "sendTo": "={{ $('Apply Rules Floor').item.json.email }}",
    "subject": "=Thanks {{ $('Apply Rules Floor').item.json.name }} — let's talk",
    "emailType": "text",
    "message": "={{ $('Apply Rules Floor').item.json.aiMessage }}",
    "options": {},
}, [{"id": "18c2f0mock02", "threadId": "18c2f0mock02", "labelIds": ["SENT"]}])

http("Notify #leads-hot", (3000, 380), "https://slack.com/api/chat.postMessage",
     "={\n  \"channel\": \"#leads-hot\",\n  \"text\": \":fire: Hot lead {{ $('Apply Rules Floor').item.json.name }} ({{ $('Apply Rules Floor').item.json.score }})\",\n  \"blocks\": [{\"type\": \"actions\", \"elements\": [{\"type\": \"button\", \"text\": {\"type\": \"plain_text\", \"text\": \"Claim\"}, \"action_id\": \"claim_lead\"}]}]\n}",
     [{"ok": True, "channel": "C0MOCKHOT", "ts": "1793347200.000200"}])

node("Notify #leads-queue", "n8n-nodes-base.slack", 2.6, (3000, 580), {
    "select": "channel",
    "channelId": {"__rl": True, "mode": "name", "value": "#leads-queue"},
    "text": "=New warm lead: {{ $('Apply Rules Floor').item.json.name }} <{{ $('Apply Rules Floor').item.json.email }}> — score {{ $('Apply Rules Floor').item.json.score }}",
    "otherOptions": {},
}, [{"ok": True, "channel": "C0MOCKQUE", "ts": "1793347200.000300"}])

sheet("Cold Lead", (3000, 780), "Cold",
      [{"row_number": 203, "email": "alex.chen@acme-corp.com", "score": 32, "tier": "cold"}])


def sticky(name, pos, w, h, color, text):
    node(name, "n8n-nodes-base.stickyNote", 1, pos, {
        "content": text, "width": w, "height": h, "color": color})


sticky("Note Capture", (160, 470), 360, 200, 3,
       "## Capture & Normalize\nWeb Form + Facebook Lead Ads\nUnified lead structure + trims\nCRM Sync\n- GoHighLevel: n8n-nodes-base.highLevel\n- Close.io: n8n-nodes-base.httpRequest")
sticky("Note Validate", (440, 720), 400, 200, 4,
       "## Validate & Dedup\nEmail + name non-empty check\nSearch HubSpot by email → check duplicate\nSubmission fields: name/email/phone/record\nDuplicate submission → log only, no action")
sticky("Note AI", (880, 720), 420, 200, 5,
       "## AI + Rules Score\nGPT-4o: output score/text/reason/message\nFloor rule: corp email + budget + long msg\nTry/catch fallback: warm / 50+")
sticky("Note CRM", (2220, 980), 560, 200, 7,
       "## CRM + Outreach + Notify\nNew contacts:\n- Hot: First-Touch Email + HubSpot + Notify #leads-hot (Claim button)\n- Warm: HubSpot + Notify #leads-queue")

# ---------- connections ----------
link("Form Lead In", "Scoring Rules (edit here)")
link("Scoring Rules (edit here)", "Normalize (Web)")
link("Normalize (Web)", "Validate Lead")
link("Validate Lead", "Log Incomplete Lead", 0)
link("Validate Lead", "Ask for Details", 1)
link("Validate Lead", "Search by Email", 2)
link("Search by Email", "Is Duplicate?")
link("Is Duplicate?", "Log Duplicate Lead", 0)
link("Is Duplicate?", "Score Lead (LLM)", 1)
link("Score Lead (LLM)", "Parse Score")
link("Parse Score", "Apply Rules Floor")
link("Apply Rules Floor", "Is New Contact?")
link("Is New Contact?", "Create Contact", 0)
link("Is New Contact?", "Is Auto Followup?", 1)
link("Is Auto Followup?", "Update Contact", 0)
link("Is Auto Followup?", "Prepare Update Diff", 1)
link("Prepare Update Diff", "Notify Sales of Update")
link("Create Contact", "Tier Router")
link("Update Contact", "Tier Router")
link("Tier Router", "First-Touch Email", 0)
link("Tier Router", "Notify #leads-hot", 0)
link("Tier Router", "Notify #leads-queue", 1)
link("Tier Router", "Cold Lead", 2)

workflow = {
    "id": "LeadCaptureCRM01",
    "name": "Lead Capture + CRM",
    "active": False,
    "nodes": nodes,
    "connections": connections,
    "pinData": pin,
    "settings": {"executionOrder": "v1"},
    "tags": [],
}

# Mock credentials so service nodes show no "credentials missing" warning
MOCK_CREDS = {
    "n8n-nodes-base.googleSheets": ("googleSheetsOAuth2Api", "mockGSheets00001", "Google Sheets (mock)",
                                    {"clientId": "mock-client-id.apps.googleusercontent.com", "clientSecret": "mock-secret"}),
    "n8n-nodes-base.gmail": ("gmailOAuth2", "mockGmail0000001", "Gmail (mock)",
                             {"clientId": "mock-client-id.apps.googleusercontent.com", "clientSecret": "mock-secret"}),
    "n8n-nodes-base.hubspot": ("hubspotAppToken", "mockHubspot00001", "HubSpot (mock)", {"appToken": "pat-mock-000000"}),
    "@n8n/n8n-nodes-langchain.openAi": ("openAiApi", "mockOpenAi000001", "OpenAI (mock)", {"apiKey": "sk-mock-000000"}),
    "n8n-nodes-base.slack": ("slackApi", "mockSlack0000001", "Slack (mock)", {"accessToken": "xoxb-mock-000000"}),
}
for n in nodes:
    if n["type"] in MOCK_CREDS:
        ctype, cid, cname, _ = MOCK_CREDS[n["type"]]
        n["credentials"] = {ctype: {"id": cid, "name": cname}}

with open("mock-credentials.json", "w") as f:
    json.dump([{"id": cid, "name": cname, "type": ctype, "data": data}
               for ctype, cid, cname, data in MOCK_CREDS.values()], f, indent=2)

with open("lead-capture-crm.json", "w") as f:
    json.dump(workflow, f, ensure_ascii=False, indent=2)
print(f"{len(nodes)} nodes, {len(pin)} pinned")
