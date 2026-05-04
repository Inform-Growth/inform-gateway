# Frontend Inline Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent inline documentation to `admin_dashboard.html` across all 8 tabs, with tiered depth — one-sentence descriptions on simple tabs, field-level helper text and examples on complex ones.

**Architecture:** All changes are pure HTML edits to a single file. No JavaScript, no CSS, no backend changes. Helper text uses the existing `var(--text-muted)` color and `0.82rem` font size already established in the file.

**Tech Stack:** HTML, inline styles (existing design tokens only)

---

## File Map

| File | Changes |
|------|---------|
| `remote-gateway/core/admin_dashboard.html` | All edits — 8 sections modified |

---

### Task 1: Executive tab — Tool Health and Sankey descriptions

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html` (lines ~606, ~623)

- [ ] **Step 1: Verify the target lines exist**

```bash
grep -n "Tool Flow Patterns\|Tool Health" remote-gateway/core/admin_dashboard.html
```

Expected output includes both strings with line numbers.

- [ ] **Step 2: Add description under "Tool Flow Patterns" chart title**

Find:
```html
        <div class="chart-title">Tool Flow Patterns</div>
        <div id="sankey-container"></div>
```

Replace with:
```html
        <div class="chart-title">Tool Flow Patterns</div>
        <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.5rem;">Each band shows a tool-to-tool transition sequence in agent sessions. Wider bands = more frequent sequences.</p>
        <div id="sankey-container"></div>
```

- [ ] **Step 3: Add description under "Tool Health" section title**

Find:
```html
      <div class="section-title">Tool Health</div>
      <table id="health-table">
```

Replace with:
```html
      <div class="section-title">Tool Health</div>
      <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem;">Click any column header to sort. High Error Rate flags tools with ≥5% errors over ≥10 calls. Click any row to open the full log drawer for that tool.</p>
      <table id="health-table">
```

- [ ] **Step 4: Verify**

```bash
grep -n "Wider bands\|High Error Rate flags" remote-gateway/core/admin_dashboard.html
```

Expected: both strings appear.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "docs: add inline descriptions to Executive tab"
```

---

### Task 2: Ops tab — Users and Permissions descriptions

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html` (lines ~649, ~677)

- [ ] **Step 1: Verify targets**

```bash
grep -n '"section-title">Users\|"section-title">Permissions' remote-gateway/core/admin_dashboard.html
```

Expected: both appear once each.

- [ ] **Step 2: Add description under "Users" section title**

Find:
```html
        <div class="section-title">Users</div>
        <div id="users-table-wrap">
```

Replace with:
```html
        <div class="section-title">Users</div>
        <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem;">Each operator and agent gets its own API key. Copy the key immediately after creation — it won't be shown again.</p>
        <div id="users-table-wrap">
```

- [ ] **Step 3: Add description under "Permissions" section title**

Find:
```html
        <div class="section-title">Permissions</div>
        <div id="perms-placeholder">Select a user to manage permissions.</div>
```

Replace with:
```html
        <div class="section-title">Permissions</div>
        <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem;">Enable or disable individual tools for the selected user. Disabling a tool hides it from their <code>tools/list</code> and blocks calls at runtime.</p>
        <div id="perms-placeholder">Select a user to manage permissions.</div>
```

- [ ] **Step 4: Verify**

```bash
grep -n "Copy the key immediately\|blocks calls at runtime" remote-gateway/core/admin_dashboard.html
```

Expected: both strings appear.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "docs: add inline descriptions to Ops tab"
```

---

### Task 3: Tools, Logs, and Tasks tab descriptions

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html` (lines ~698, ~723, ~770)

- [ ] **Step 1: Verify targets**

```bash
grep -n '"section-title">Registered Tools\|"section-title">Raw Tool Logs\|"section-title">Tasks' remote-gateway/core/admin_dashboard.html
```

Expected: all three appear once each.

- [ ] **Step 2: Add description under "Registered Tools" section title**

Find:
```html
      <div class="section-title">Registered Tools</div>
      <table id="tools-table">
```

Replace with:
```html
      <div class="section-title">Registered Tools</div>
      <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem;">All tools registered to this gateway, including proxied integrations. Use the Global toggle to disable a tool for every user at once — no restart required.</p>
      <table id="tools-table">
```

- [ ] **Step 3: Add description under "Raw Tool Logs" section title**

Find:
```html
      <div class="section-title">Raw Tool Logs</div>
      <div style="display:flex;gap:0.6rem;margin-bottom:1rem;flex-wrap:wrap;">
```

Replace with:
```html
      <div class="section-title">Raw Tool Logs</div>
      <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem;">Every tool call logged in real time. Click any row to inspect the full request and response. Use filters to isolate errors or activity from a specific user.</p>
      <div style="display:flex;gap:0.6rem;margin-bottom:1rem;flex-wrap:wrap;">
```

- [ ] **Step 4: Add description under "Tasks" section title**

Find:
```html
        <div class="section-title">Tasks</div>
        <div style="margin-bottom:0.75rem;">
          <select id="tasks-filter-status"
```

Replace with:
```html
        <div class="section-title">Tasks</div>
        <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem;">Tasks are declared by agents at session start via <code>declare_intent</code>. Each represents one user goal. Click a task to see every tool call made while working toward it.</p>
        <div style="margin-bottom:0.75rem;">
          <select id="tasks-filter-status"
```

- [ ] **Step 5: Verify**

```bash
grep -n "Global toggle\|inspect the full request\|declare_intent" remote-gateway/core/admin_dashboard.html
```

Expected: all three strings appear.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "docs: add inline descriptions to Tools, Logs, and Tasks tabs"
```

---

### Task 4: Org Profile tab — field helper text and richer placeholders

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html` (lines ~831–841)

- [ ] **Step 1: Verify targets**

```bash
grep -n 'profile-tone\|profile-icp\|profile-vocab_rules' remote-gateway/core/admin_dashboard.html
```

Expected: all three input IDs appear.

- [ ] **Step 2: Update Tone field — add helper text and richer placeholder**

Find:
```html
      <div style="margin-bottom:1rem;">
        <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Tone</label>
        <input id="profile-tone" type="text" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="professional, concise">
      </div>
```

Replace with:
```html
      <div style="margin-bottom:1rem;">
        <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Tone</label>
        <p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.3rem;">How agents should communicate in outputs and drafted messages.</p>
        <input id="profile-tone" type="text" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="professional, concise">
      </div>
```

- [ ] **Step 3: Update ICP field — add helper text and richer placeholder**

Find:
```html
      <div style="margin-bottom:1rem;">
        <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">ICP</label>
        <input id="profile-icp" type="text" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="B2B SaaS, 10-200 employees">
      </div>
```

Replace with:
```html
      <div style="margin-bottom:1rem;">
        <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">ICP</label>
        <p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.3rem;">Ideal Customer Profile. Agents use this to filter and prioritize prospects.</p>
        <input id="profile-icp" type="text" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="B2B SaaS, 10–200 employees, US-based">
      </div>
```

- [ ] **Step 4: Update Vocab Rules field — add helper text and richer placeholder**

Find:
```html
      <div style="margin-bottom:1rem;">
        <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Vocab Rules</label>
        <textarea id="profile-vocab_rules" rows="3" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="Always say 'prospect' not 'lead'..."></textarea>
      </div>
```

Replace with:
```html
      <div style="margin-bottom:1rem;">
        <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Vocab Rules</label>
        <p style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.3rem;">Terminology rules applied to all agent output.</p>
        <textarea id="profile-vocab_rules" rows="3" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="Say 'prospect' not 'lead'. Use first name only in emails."></textarea>
      </div>
```

- [ ] **Step 5: Verify**

```bash
grep -n "filter and prioritize prospects\|How agents should communicate\|Terminology rules" remote-gateway/core/admin_dashboard.html
```

Expected: all three strings appear.

- [ ] **Step 6: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "docs: add field helper text and richer placeholders to Org Profile tab"
```

---

### Task 5: Skills tab — section description and updated modal hint

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html` (lines ~852–875)

- [ ] **Step 1: Verify targets**

```bash
grep -n 'id="skills-table-wrap"\|Use {variable} for placeholders' remote-gateway/core/admin_dashboard.html
```

Expected: both appear once each.

- [ ] **Step 2: Add section description above the skills table**

Find:
```html
      <div id="skills-table-wrap"></div>
    </div>

    <div id="skill-modal"
```

Replace with:
```html
      <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:0.75rem;">Skills are reusable prompt templates agents can invoke via <code>run_skill</code>. Use them for recurring workflows like morning briefings or prospect research.</p>
      <div id="skills-table-wrap"></div>
    </div>

    <div id="skill-modal"
```

- [ ] **Step 3: Update Prompt Template hint in the modal**

Find:
```html
          <p style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.3rem;">Use {variable} for placeholders filled by run_skill.</p>
```

Replace with:
```html
          <p style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.3rem;">Use <code>{variable}</code> for runtime inputs. Example: <code>Research {company} and draft a 3-bullet outreach for {contact_name}.</code></p>
```

- [ ] **Step 4: Verify**

```bash
grep -n "recurring workflows\|draft a 3-bullet outreach" remote-gateway/core/admin_dashboard.html
```

Expected: both strings appear.

- [ ] **Step 5: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "docs: add inline descriptions to Skills tab and modal"
```

---

### Task 6: Tool Hints tab — full explainer and modal field help

**Files:**
- Modify: `remote-gateway/core/admin_dashboard.html` (lines ~886–925)

- [ ] **Step 1: Verify targets**

```bash
grep -n "Hints are injected into tool responses\|hint-modal-hint\|hint-modal-rules\|hint-modal-sensitivity" remote-gateway/core/admin_dashboard.html
```

Expected: the one-liner and all three modal field IDs appear.

- [ ] **Step 2: Replace the one-liner with a full explainer block**

Find:
```html
      <p style="font-size:0.82rem;color:var(--text-muted);margin-bottom:1rem;">Hints are injected into tool responses as <code>meta</code> fields to guide interpretation.</p>
```

Replace with:
```html
      <div style="background:var(--cream-dark);border-left:3px solid var(--green-mid);padding:0.75rem 1rem;margin-bottom:1rem;font-size:0.82rem;line-height:1.6;">
        <strong style="display:block;margin-bottom:0.3rem;">What are Tool Hints?</strong>
        When an agent calls a tool through the gateway, the response is automatically wrapped with a <code>meta</code> block containing your hint. The agent reads this on every call — like a sticky note attached to each tool response. Use hints to correct misinterpretations, enforce call discipline, and tag data sensitivity, without touching any code.
      </div>
```

- [ ] **Step 3: Add helper text to the Interpretation Hint field in the modal**

Find:
```html
          <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Interpretation Hint</label>
          <textarea id="hint-modal-hint" rows="3" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;"></textarea>
```

Replace with:
```html
          <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Interpretation Hint</label>
          <p style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.3rem;">How should the agent read this data?</p>
          <textarea id="hint-modal-hint" rows="3" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="score > 80 = high priority. Ignore 'seniority' field — unreliable for VP-level titles."></textarea>
```

- [ ] **Step 4: Add helper text to the Usage Rules field in the modal**

Find:
```html
          <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Usage Rules</label>
          <textarea id="hint-modal-rules" rows="3" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;"></textarea>
```

Replace with:
```html
          <label style="display:block;font-size:0.82rem;font-weight:700;margin-bottom:0.3rem;">Usage Rules</label>
          <p style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.3rem;">When and how should this tool be called?</p>
          <textarea id="hint-modal-rules" rows="3" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-family:'Courier New',monospace;font-size:0.82rem;" placeholder="Always pass company domain when searching by name. Never call more than once per person in a session."></textarea>
```

- [ ] **Step 5: Add helper text below the Data Sensitivity select**

Find:
```html
          <select id="hint-modal-sensitivity" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-size:0.82rem;">
            <option value="public">public</option>
            <option value="internal" selected>internal</option>
            <option value="confidential">confidential</option>
          </select>
        </div>
        <div style="display:flex;justify-content:flex-end;gap:0.5rem;margin-top:1rem;">
```

Replace with:
```html
          <select id="hint-modal-sensitivity" style="width:100%;padding:0.4rem 0.6rem;border:1px solid var(--border);background:var(--cream);font-size:0.82rem;">
            <option value="public">public</option>
            <option value="internal" selected>internal</option>
            <option value="confidential">confidential</option>
          </select>
          <p style="font-size:0.75rem;color:var(--text-muted);margin-top:0.3rem;"><strong>public</strong> = can be shared freely · <strong>internal</strong> = do not surface in external-facing outputs · <strong>confidential</strong> = treat like PII; do not log or quote directly</p>
        </div>
        <div style="display:flex;justify-content:flex-end;gap:0.5rem;margin-top:1rem;">
```

- [ ] **Step 6: Verify**

```bash
grep -n "sticky note attached\|How should the agent read\|When and how should this tool\|treat like PII" remote-gateway/core/admin_dashboard.html
```

Expected: all four strings appear.

- [ ] **Step 7: Commit**

```bash
git add remote-gateway/core/admin_dashboard.html
git commit -m "docs: add full explainer and field help to Tool Hints tab"
```

---

## Self-Review Against Spec

| Spec requirement | Task |
|---|---|
| Executive: Tool Health description + sort/click note | Task 1 |
| Executive: Sankey "wider bands" description | Task 1 |
| Ops: Users API key copy warning | Task 2 |
| Ops: Permissions enable/disable explanation | Task 2 |
| Tools: Global toggle explanation | Task 3 |
| Logs: click-to-inspect + filter guidance | Task 3 |
| Tasks: declare_intent + click-to-drilldown | Task 3 |
| Org Profile: ICP/Tone/Vocab helper text + richer placeholders | Task 4 |
| Skills: section description + richer modal hint | Task 5 |
| Tool Hints: full explainer block replacing one-liner | Task 6 |
| Tool Hints modal: Interpretation Hint helper + placeholder | Task 6 |
| Tool Hints modal: Usage Rules helper + placeholder | Task 6 |
| Tool Hints modal: Data Sensitivity helper text | Task 6 |
| Visual treatment: var(--text-muted), 0.82rem, no new CSS | All tasks ✓ |
| No backend/API changes | N/A ✓ |
