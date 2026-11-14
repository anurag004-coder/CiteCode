const menuButton = document.querySelector(".menu-toggle");
const nav = document.querySelector(".nav-links");

menuButton?.addEventListener("click", () => {
  const isOpen = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", String(!isOpen));
  menuButton.setAttribute("aria-label", isOpen ? "Open navigation" : "Close navigation");
  nav?.classList.toggle("is-open", !isOpen);
});

nav?.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    nav.classList.remove("is-open");
    menuButton?.setAttribute("aria-expanded", "false");
    menuButton?.setAttribute("aria-label", "Open navigation");
  });
});

const stages = {
  index: {
    label: "REPOSITORY INDEX",
    title: "Start with the shape of the code.",
    description: "A repository is read at a known commit. Code-aware chunks preserve the structure that helps an explanation make sense.",
    caption: "Code structure stays attached to its source.",
    visual: `<div class="index-window"><div class="window-bar"><span></span><span></span><span></span><small>atlas-web / main · 9f32c8a</small></div><div class="index-progress"><i></i></div><div class="index-status"><span>Structure-aware indexing</span><b>Complete</b></div><div class="index-stats"><div><strong>128</strong><span>FILES READ</span></div><div><strong>642</strong><span>CODE CHUNKS</span></div><div><strong>18</strong><span>DOC SECTIONS</span></div></div><div class="index-files"><span>✓</span> src/auth/middleware.ts <small>12 symbols</small></div><div class="index-files"><span>✓</span> docs/architecture.md <small>6 sections</small></div></div><div class="index-aside-card"><span>INDEXED VERSION</span><b>9f32c8a</b><p>Every citation points back to this snapshot.</p><span class="aside-arrow">↗</span></div>`,
  },
  answer: {
    label: "EVIDENCE-FIRST ANSWERS",
    title: "The source is part of the answer.",
    description: "Hybrid retrieval finds both exact code symbols and conceptual matches. The answer is checked against retrieved lines before it appears.",
    caption: "Open the cited lines to verify the explanation.",
    visual: `<div class="workflow-alt"><div class="workflow-alt-card"><b>Question</b>Where does a request get authenticated?<br><span>→ hybrid search · 8 evidence chunks</span></div><div class="workflow-alt-card"><b>Verified claim</b>Auth middleware checks the session before protected routes.<br><span>↗ src/auth/middleware.ts · 42–68</span></div><div class="workflow-alt-card"><b>Evidence gate</b>Evidence is sufficient to support a short answer.<br><span>✓ line range checked</span></div><div class="workflow-alt-card"><b>When evidence is missing</b>Refuse clearly and show what was searched.<br><span>— no fabricated citations</span></div></div>`,
  },
  guide: {
    label: "PERSONAL ONBOARDING",
    title: "A map that meets you where you are.",
    description: "A developer’s goal shapes the guide: learn the architecture, run the app, trace a request, or find a first small task.",
    caption: "A focused path beats a dump of every file.",
    visual: `<div class="workflow-alt"><div class="workflow-alt-card"><b>Your goal</b>I know React and want to make a small UI change.<br><span>LEVEL · NEW TO THIS REPOSITORY</span></div><div class="workflow-alt-card"><b>First, get it running</b>Follow the setup guide, then open the main route.<br><span>↗ README.md · 18–31</span></div><div class="workflow-alt-card"><b>Trace the page</b>Route → page component → shared shell.<br><span>↗ src/routes.tsx · 22–41</span></div><div class="workflow-alt-card"><b>Try this next</b>Review a beginner issue connected to the UI.<br><span>3 SOURCES ATTACHED</span></div></div>`,
  },
  contribute: {
    label: "HUMAN-APPROVED ACTION",
    title: "Move forward without handing over control.",
    description: "The agent can prepare an issue or pull request draft. A person sees the target and exact content before a separate handler executes it.",
    caption: "Preview first. Approve explicitly. Verify the result.",
    visual: `<div class="workflow-alt"><div class="workflow-alt-card"><b>Suggested issue</b>Document session expiry behavior<br><span>WHY IT FITS · CLEAR SCOPE · RELATED CODE FOUND</span></div><div class="workflow-alt-card"><b>Proposed action</b>Draft only — no GitHub write has happened.<br><span>PAYLOAD HASH · 6d88…c21a</span></div><div class="workflow-alt-card"><b>Human review</b>Check title, body, repository, and destination.<br><span>WAITING FOR YOUR APPROVAL</span></div><div class="workflow-alt-card"><b>After approval</b>Execute with a separate credential, then read back.<br><span>✓ RESULT VERIFIED</span></div></div>`,
  },
};

const tabs = [...document.querySelectorAll(".workflow-tab")];
const panel = document.querySelector(".workflow-panel");
function selectStage(name, moveFocus = false) {
  const stage = stages[name];
  if (!stage || !panel) return;
  tabs.forEach((tab) => {
    const active = tab.dataset.step === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.setAttribute("tabindex", active ? "0" : "-1");
    if (active && moveFocus) tab.focus();
  });
  document.querySelector("#workflow-label").textContent = stage.label;
  document.querySelector("#workflow-title").textContent = stage.title;
  document.querySelector("#workflow-description").textContent = stage.description;
  document.querySelector("#workflow-caption").textContent = stage.caption;
  document.querySelector("#workflow-count").textContent = String(tabs.findIndex((tab) => tab.dataset.step === name) + 1).padStart(2, "0");
  document.querySelector("#workflow-visual").innerHTML = stage.visual;
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectStage(tab.dataset.step));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    selectStage(tabs[next].dataset.step, true);
  });
});

// Reveal sections as they enter view, while keeping content visible without JS.
document.documentElement.classList.add("js-ready");
const revealTargets = document.querySelectorAll(".problem-grid, .statement-band, .journey-step, .feature-card, .useful-copy, .workflow-demo, .faq-list, .final-cta");
revealTargets.forEach((element) => element.classList.add("reveal"));
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08 });
  revealTargets.forEach((element) => observer.observe(element));
} else {
  revealTargets.forEach((element) => element.classList.add("is-visible"));
}

const localApiHost = ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ? window.location.hostname
  : "localhost";
const API_BASE = window.CODEBASE_API_URL || `http://${localApiHost}:8001`;
const DEMO_EMAIL = "example123@gmail.com";
const DEMO_PASSWORD = "Admin@123";
const authScreen = document.querySelector("#auth-screen");
const dashboardScreen = document.querySelector("#dashboard-screen");
const loginForm = document.querySelector("#login-form");
const authMessage = document.querySelector("#auth-message");
const dashboardMessage = document.querySelector("#dashboard-message");
const welcomeModal = document.querySelector("#welcome-modal");
const dashboardTitles = {
  overview: "Overview",
  ask: "Ask the code",
  onboarding: "Onboarding guide",
  issues: "Good first issues",
  changes: "Changes",
  actions: "Action approvals",
  evaluation: "Evaluation",
};
let dashboardUser = null;
let dashboardLoaded = false;
let indexedRepositories = [];

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string"
      ? data.detail
      : Array.isArray(data.detail)
        ? data.detail.map((issue) => issue.msg).filter(Boolean).join(" ")
        : "The request could not be completed.";
    throw new Error(detail);
  }
  return data;
}

function showAuthScreen() {
  document.body.classList.add("app-mode");
  if (authScreen) authScreen.hidden = false;
  if (dashboardScreen) dashboardScreen.hidden = true;
  const email = document.querySelector("#login-email");
  const password = document.querySelector("#login-password");
  if (email) email.value = DEMO_EMAIL;
  if (password) password.value = DEMO_PASSWORD;
  if (authMessage) authMessage.textContent = "";
  apiRequest("/auth/me").then(() => {
    if (["#auth", "#auth-screen", "#login", "#signup"].includes(window.location.hash)) window.location.hash = "#dashboard";
  }).catch(() => {});
}

function showDashboardView(viewName, { refreshActions = true } = {}) {
  const name = dashboardTitles[viewName] ? viewName : "overview";
  document.querySelectorAll("[data-app-view]").forEach((view) => {
    view.hidden = view.dataset.appView !== name;
  });
  document.querySelectorAll("[data-dashboard-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.dashboardView === name);
  });
  const title = document.querySelector("#dashboard-view-title");
  if (title) title.textContent = dashboardTitles[name];
  if (name === "changes") {
    const repoId = document.querySelector("#changes-repo")?.value;
    if (repoId) loadSavedChanges(repoId);
  }
  if (name === "actions" && refreshActions) loadActions();
}

function setDashboardMessage(message, isError = false) {
  if (!dashboardMessage) return;
  dashboardMessage.textContent = message || "";
  dashboardMessage.classList.toggle("is-error", Boolean(isError));
  dashboardMessage.classList.toggle("is-visible", Boolean(message));
}

async function enterDashboard() {
  document.body.classList.add("app-mode");
  if (authScreen) authScreen.hidden = true;
  if (dashboardScreen) dashboardScreen.hidden = false;
  showDashboardView("overview");
  try {
    dashboardUser = await apiRequest("/auth/me");
    const email = document.querySelector("#dashboard-user-email");
    if (email) email.textContent = dashboardUser.email;
    const guideLevel = document.querySelector("#guide-level");
    const guideGoal = document.querySelector("#guide-goal");
    if (guideLevel) guideLevel.value = dashboardUser.experience_level || "";
    if (guideGoal) guideGoal.value = dashboardUser.onboarding_goal || "";
    if (!dashboardLoaded) {
      await loadRepositories();
      dashboardLoaded = true;
    }
    if (dashboardUser.onboarding_completed) closeWelcomeModal();
    else openWelcomeModal();
  } catch (error) {
    dashboardUser = null;
    dashboardLoaded = false;
    closeWelcomeModal();
    window.location.hash = "#auth";
    if (authMessage) authMessage.textContent = error.message;
  }
}

function openWelcomeModal(editing = false) {
  if (!welcomeModal) return;
  welcomeModal.dataset.editing = String(editing);
  const title = document.querySelector("#welcome-modal-title");
  const description = document.querySelector("#welcome-modal-description");
  const kicker = document.querySelector("#welcome-modal-kicker");
  const submitButton = document.querySelector("#welcome-form button[type='submit']");
  const skipButton = document.querySelector("#welcome-skip");
  if (title) title.innerHTML = editing ? "Tune your<br /><em>onboarding guide.</em>" : "Welcome to your<br /><em>codebase workspace.</em>";
  if (description) description.textContent = editing
    ? "Update your preferences to change the language, setup steps, and pace of future guides."
    : "A little context helps shape a useful first guide. You can skip this and set it later.";
  if (kicker) kicker.textContent = editing ? "GUIDE PREFERENCES" : "YOUR FIRST VISIT";
  if (submitButton) submitButton.innerHTML = editing
    ? "Save preferences <span aria-hidden='true'>↗</span>"
    : "OK, continue <span aria-hidden='true'>↗</span>";
  if (skipButton) skipButton.hidden = editing;
  const level = document.querySelector("#welcome-level");
  const goal = document.querySelector("#welcome-goal");
  if (level) level.value = dashboardUser?.experience_level || "";
  if (goal) goal.value = dashboardUser?.onboarding_goal || "";
  document.querySelectorAll("input[name='welcome-language']").forEach((input) => {
    input.checked = dashboardUser?.languages_known?.includes(input.value) || false;
  });
  const os = document.querySelector("#welcome-os");
  const time = document.querySelector("#welcome-time");
  const explanationLanguage = document.querySelector("#welcome-explanation-language");
  if (os) os.value = dashboardUser?.setup_os || "linux";
  if (time) time.value = dashboardUser?.time_available || "1_day";
  if (explanationLanguage) explanationLanguage.value = dashboardUser?.explanation_language || "English";
  const dockerValue = dashboardUser?.uses_docker === false ? "no" : "yes";
  const dockerRadio = document.querySelector(`input[name='welcome-docker'][value='${dockerValue}']`);
  if (dockerRadio) dockerRadio.checked = true;
  syncWelcomeLanguages();
  const message = document.querySelector("#welcome-message");
  if (message) message.textContent = "";
  welcomeModal.hidden = false;
  window.setTimeout(() => level?.focus(), 0);
}

function syncWelcomeLanguages(changedInput) {
  const inputs = [...document.querySelectorAll("input[name='welcome-language']")];
  const noneOption = inputs.find((input) => input.value === "None of these");
  if (changedInput?.value === "None of these" && changedInput.checked) {
    inputs.filter((input) => input !== changedInput).forEach((input) => { input.checked = false; });
  } else if (changedInput?.checked && noneOption) {
    noneOption.checked = false;
  }
  const selected = inputs.filter((input) => input.checked);
  const first = inputs[0];
  first?.setCustomValidity(selected.length ? "" : "Choose at least one language, or select ‘None of these’.");
}

document.querySelectorAll("input[name='welcome-language']").forEach((input) => {
  input.addEventListener("change", () => syncWelcomeLanguages(input));
});

function closeWelcomeModal() {
  if (!welcomeModal || welcomeModal.hidden) return;
  const editing = welcomeModal.dataset.editing === "true";
  welcomeModal.hidden = true;
  welcomeModal.dataset.editing = "false";
  document.querySelector(editing ? "#edit-onboarding-preferences" : "#repo-url")?.focus();
}

welcomeModal?.addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  const controls = [...welcomeModal.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href]")];
  if (!controls.length) return;
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

async function saveWelcomeProfile(event, skip = false) {
  if (event) event.preventDefault();
  const level = skip ? null : (document.querySelector("#welcome-level")?.value || null);
  const goal = skip ? null : (document.querySelector("#welcome-goal")?.value || null);
  const languagesKnown = skip ? [] : [...document.querySelectorAll("input[name='welcome-language']:checked")].map((input) => input.value);
  const setupOs = skip ? "linux" : (document.querySelector("#welcome-os")?.value || "linux");
  const usesDocker = skip ? true : document.querySelector("input[name='welcome-docker']:checked")?.value !== "no";
  const timeAvailable = skip ? "1_day" : (document.querySelector("#welcome-time")?.value || "1_day");
  const explanationLanguage = skip ? "English" : (document.querySelector("#welcome-explanation-language")?.value || "English");
  const message = document.querySelector("#welcome-message");
  const submitButton = document.querySelector("#welcome-form button[type='submit']");
  const skipButton = document.querySelector("#welcome-skip");
  if (message) message.textContent = "Saving your preferences…";
  if (submitButton) submitButton.disabled = true;
  if (skipButton) skipButton.disabled = true;
  try {
    dashboardUser = await apiRequest("/auth/onboarding", {
      method: "POST",
      body: JSON.stringify({
        experience_level: level,
        goal,
        languages_known: languagesKnown,
        setup_os: setupOs,
        uses_docker: usesDocker,
        time_available: timeAvailable,
        explanation_language: explanationLanguage,
      }),
    });
    const guideLevel = document.querySelector("#guide-level");
    const guideGoal = document.querySelector("#guide-goal");
    if (guideLevel) guideLevel.value = dashboardUser.experience_level || "";
    if (guideGoal) guideGoal.value = dashboardUser.onboarding_goal || "";
    closeWelcomeModal();
    setDashboardMessage("Preferences saved. Open the onboarding guide to create a source-linked learning path.");
  } catch (error) {
    if (message) message.textContent = error.message;
  } finally {
    if (submitButton) submitButton.disabled = false;
    if (skipButton) skipButton.disabled = false;
  }
}

document.querySelector("#welcome-form")?.addEventListener("submit", saveWelcomeProfile);
document.querySelector("#welcome-skip")?.addEventListener("click", () => saveWelcomeProfile(null, true));
document.querySelector("#edit-onboarding-preferences")?.addEventListener("click", () => openWelcomeModal(true));

function routeApp() {
  const route = window.location.hash;
  if (route === "#dashboard") {
    enterDashboard();
  } else if (["#auth", "#auth-screen", "#login", "#signup"].includes(route)) {
    showAuthScreen();
  } else {
    document.body.classList.remove("app-mode");
    if (authScreen) authScreen.hidden = true;
    if (dashboardScreen) dashboardScreen.hidden = true;
  }
}

async function submitAuthForm(form, endpoint) {
  const submitButton = form.querySelector("button[type='submit']");
  const formData = new FormData(form);
  if (authMessage) authMessage.textContent = "";
  if (submitButton) submitButton.disabled = true;
  try {
    await apiRequest(endpoint, {
      method: "POST",
      body: JSON.stringify({ email: formData.get("email"), password: formData.get("password") }),
    });
    dashboardLoaded = false;
    window.location.hash = "#dashboard";
  } catch (error) {
    if (authMessage) authMessage.textContent = error.message;
  } finally {
    if (submitButton) submitButton.disabled = false;
  }
}

loginForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuthForm(loginForm, "/auth/login");
});

document.querySelectorAll("[data-dashboard-view]").forEach((button) => {
  button.addEventListener("click", () => {
    showDashboardView(button.dataset.dashboardView);
    setDashboardMessage("");
  });
});

async function logout() {
  try {
    await apiRequest("/auth/logout", { method: "POST" });
  } catch (error) {
    // The server may already be unreachable or the session may already have expired.
  }
  dashboardUser = null;
  dashboardLoaded = false;
  window.location.hash = "#top";
}

document.querySelectorAll("[data-logout]").forEach((button) => button.addEventListener("click", logout));

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderActionProposals(data) {
  const container = document.querySelector("#action-results");
  const connection = document.querySelector("#actions-connection");
  if (!container) return;
  if (connection) {
    connection.classList.toggle("is-disabled", !data.github_write_configured);
    connection.textContent = data.github_write_configured
      ? "GitHub write credential is configured. Nothing is sent until you approve an exact proposal."
      : "GitHub write credential is not configured. You can prepare and review proposals, but approval stays disabled.";
  }
  container.replaceChildren();
  if (!data.proposals?.length) {
    container.append(makeElement("div", "empty-repo-state", "No proposals yet. Prepare one above to see its exact review preview here."));
    return;
  }
  data.proposals.forEach((proposal) => {
    const card = makeElement("article", "action-proposal-card");
    const header = makeElement("div", "action-proposal-header");
    const title = makeElement("h3", "", proposal.payload.title);
    const status = makeElement("span", `action-status status-${proposal.status}`, proposal.status.replaceAll("_", " ").toUpperCase());
    header.append(title, status);
    const actionNames = { issue: "Issue", draft_pr: "Draft pull request from existing branch", code_pr: "Code fix + draft pull request" };
    const target = makeElement("p", "action-target", `${actionNames[proposal.action_type] || "GitHub action"} · ${proposal.repository}`);
    const hash = makeElement("code", "action-hash", `Reviewed payload SHA-256 · ${proposal.payload_hash}`);
    const created = makeElement("small", "action-created", `Prepared ${new Date(proposal.created_at).toLocaleString()}`);
    card.append(header, target);
    if (proposal.action_type === "code_pr") {
      const metadata = makeElement("p", "action-target", `Target ${proposal.payload.base_branch} at ${proposal.payload.base_sha} · New branch ${proposal.payload.branch}`);
      card.append(metadata);
      if (proposal.payload.summary) card.append(makeElement("p", "action-summary", proposal.payload.summary));
      if (proposal.payload.issue_number) card.append(makeElement("p", "action-target", `Related issue #${proposal.payload.issue_number}`));
      (proposal.payload.changes || []).forEach((change) => {
        const file = makeElement("section", "action-file-diff");
        file.append(makeElement("h4", "", change.path));
        if (change.reason) file.append(makeElement("p", "action-target", change.reason));
        file.append(makeElement("pre", "action-diff-preview", change.diff || "No diff preview was returned."));
        card.append(file);
      });
      if (proposal.payload.validation) {
        const validation = proposal.payload.validation;
        const report = makeElement("section", `action-validation status-${validation.status}`, "");
        report.append(makeElement("h4", "", `Sandbox validation · ${validation.status.replaceAll("_", " ").toUpperCase()}`));
        report.append(makeElement("p", "action-target", validation.message || "No validation summary was returned."));
        (validation.commands || []).forEach((check) => {
          const item = makeElement("div", "action-validation-command");
          item.append(makeElement("strong", "", `${check.label} · ${check.status}${check.exit_code === null || check.exit_code === undefined ? "" : ` · exit ${check.exit_code}`}`));
          if (check.output) item.append(makeElement("pre", "action-validation-output", check.output));
          report.append(item);
        });
        card.append(report);
      }
      const description = document.createElement("details");
      description.className = "action-pr-description";
      description.append(makeElement("summary", "", "Draft pull request description"));
      description.append(makeElement("pre", "action-payload-preview", proposal.payload.body || ""));
      card.append(description);
      if (proposal.payload.validation_steps?.length) {
        card.append(makeElement("p", "action-target", `Suggested checks (not run): ${proposal.payload.validation_steps.join(" · ")}`));
      }
    } else {
      card.append(makeElement("pre", "action-payload-preview", JSON.stringify(proposal.payload, null, 2)));
    }
    card.append(hash, created);
    if (proposal.status === "pending") {
      const controls = makeElement("div", "approval-controls");
      const approvalLabel = document.createElement("label");
      approvalLabel.className = "approval-check-label";
      const approval = document.createElement("input");
      approval.type = "checkbox";
      approval.checked = false;
      approval.setAttribute("aria-label", `Approve exact GitHub payload for ${proposal.repository}`);
      const approvalText = makeElement("span", "", proposal.action_type === "code_pr"
        ? "I reviewed the exact diff, sandbox report, target branch, and pull request description above, and approve this GitHub write."
        : "I reviewed the repository and exact content above, and approve this GitHub write.");
      approvalLabel.append(approval, approvalText);
      const approve = makeElement("button", "button button-dark", proposal.action_type === "code_pr"
        ? "Approve, commit, and open draft PR"
        : "Approve and create");
      approve.type = "button";
      approve.disabled = true;
      approval.addEventListener("change", () => { approve.disabled = !data.github_write_configured || !approval.checked; });
      approve.addEventListener("click", () => approveAction(proposal, approve));
      const reject = makeElement("button", "button button-light", "Reject");
      reject.type = "button";
      reject.addEventListener("click", () => rejectAction(proposal, reject));
      controls.append(approvalLabel, approve, reject);
      card.append(controls);
    }
    if (proposal.status === "approved") {
      card.append(makeElement("p", "action-notice", "Approved. The MCP server is ready to execute this same reviewed payload."));
    }
    if (proposal.error) card.append(makeElement("p", "action-error", proposal.error));
    if (proposal.result) {
      const resultLabel = proposal.action_type === "issue" ? "issue" : "draft pull request";
      const resultLine = makeElement("p", "action-result-line", `Created ${resultLabel} #${proposal.result.number}`);
      const resultLink = makeElement("a", "", "Open on GitHub ↗");
      resultLink.href = proposal.result.html_url;
      resultLink.target = "_blank";
      resultLink.rel = "noopener noreferrer";
      resultLine.append(" · ", resultLink);
      if (proposal.result.branch_url) {
        const branchLink = makeElement("a", "", "View code branch ↗");
        branchLink.href = proposal.result.branch_url;
        branchLink.target = "_blank";
        branchLink.rel = "noopener noreferrer";
        resultLine.append(" · ", branchLink);
      }
      card.append(resultLine);
      if (proposal.result.read_after_write_verified !== undefined) {
        const checked = proposal.result.read_after_write_verified;
        card.append(makeElement(
          "p",
          checked ? "action-result-verification is-confirmed" : "action-result-verification",
          proposal.result.verification_detail || (checked
            ? "GitHub read-back matched the approved proposal."
            : "GitHub could not confirm the saved record fields."),
        ));
      }
    }
    container.append(card);
  });
}

async function loadActions() {
  try {
    renderActionProposals(await apiRequest("/actions"));
  } catch (error) {
    const container = document.querySelector("#action-results");
    if (container) container.textContent = error.message;
  }
}

async function approveAction(proposal, button) {
  button.disabled = true;
  setDashboardMessage(proposal.action_type === "code_pr"
    ? "Approval recorded. The MCP action server is committing the reviewed patch and opening a draft PR…"
    : "Approval recorded. The MCP action server is creating the reviewed GitHub item…");
  try {
    await apiRequest(`/actions/${encodeURIComponent(proposal.id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ confirm: true, payload_hash: proposal.payload_hash }),
    });
    await loadActions();
    setDashboardMessage(proposal.action_type === "code_pr"
      ? "The reviewed code fix was committed and its draft pull request was created through MCP."
      : "GitHub action completed through the approval-gated MCP tool.");
  } catch (error) {
    await loadActions();
    setDashboardMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function rejectAction(proposal, button) {
  button.disabled = true;
  try {
    await apiRequest(`/actions/${encodeURIComponent(proposal.id)}/reject`, { method: "POST" });
    await loadActions();
    setDashboardMessage("Proposal rejected. No GitHub write was made.");
  } catch (error) {
    setDashboardMessage(error.message, true);
    button.disabled = false;
  }
}

const actionTypeSelect = document.querySelector("#action-type");
function syncActionTypeFields() {
  const actionType = actionTypeSelect?.value;
  const isIssue = actionType === "issue";
  const isPr = actionType === "draft_pr";
  const isCodeFix = actionType === "code_fix";
  document.querySelector(".action-issue-fields")?.toggleAttribute("hidden", !isIssue);
  document.querySelector(".action-pr-fields")?.toggleAttribute("hidden", !isPr);
  document.querySelector(".action-code-fix-fields")?.toggleAttribute("hidden", !isCodeFix);
  const description = document.querySelector("#action-body");
  if (description) description.maxLength = isCodeFix ? 5000 : 12000;
  ["#action-head", "#action-base"].forEach((selector) => {
    const input = document.querySelector(selector);
    if (input) { input.required = isPr; input.disabled = !isPr; }
  });
}
actionTypeSelect?.addEventListener("change", syncActionTypeFields);
syncActionTypeFields();

document.querySelector("#action-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const actionType = document.querySelector("#action-type")?.value;
  const labels = document.querySelector("#action-labels")?.value.split(",").map((label) => label.trim()).filter(Boolean) || [];
  const proposal = {
    repo_id: document.querySelector("#action-repo")?.value,
    title: document.querySelector("#action-title")?.value.trim(),
    body: document.querySelector("#action-body")?.value.trim(),
    labels: actionType === "issue" ? labels : [],
  };
  let endpoint = "/actions";
  if (actionType === "draft_pr") {
    proposal.action_type = actionType;
    proposal.head = document.querySelector("#action-head")?.value.trim();
    proposal.base = document.querySelector("#action-base")?.value.trim();
  } else if (actionType === "code_fix") {
    endpoint = "/actions/code-fix";
    proposal.task = proposal.body;
    delete proposal.body;
    delete proposal.labels;
    const issueNumber = document.querySelector("#action-issue-number")?.value.trim();
    if (issueNumber) proposal.issue_number = Number(issueNumber);
  } else {
    proposal.action_type = "issue";
  }
  if (button) button.disabled = true;
  setDashboardMessage(actionType === "code_fix"
    ? "Generating a patch and running isolated repository checks. GitHub has not been contacted; this can take a minute."
    : "Saving the proposal locally for review. GitHub has not been contacted.");
  try {
    await apiRequest(endpoint, { method: "POST", body: JSON.stringify(proposal) });
    form.reset();
    syncActionTypeFields();
    await loadActions();
    setDashboardMessage(actionType === "code_fix"
      ? "Patch and sandbox report prepared. Review the diff, test output, target branch, and PR description below."
      : "Proposal prepared. Review its repository, payload, and hash below before approving.");
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});

function renderBenchmark(result) {
  const container = document.querySelector("#evaluation-results");
  if (!container) return;
  container.replaceChildren();
  const meta = makeElement("p", "benchmark-meta", `${result.dataset} · ${result.repository} · ${result.total_cases} cases · ${result.answerable_cases} answerable · ${result.unanswerable_cases} unanswerable · snapshot ${result.commit_sha.slice(0, 8)} · gold-reference coverage ${Math.round(result.gold_path_coverage * 100)}%`);
  container.append(meta);
  const scoreGrid = makeElement("div", "benchmark-score-grid");
  ["keyword", "semantic", "hybrid"].forEach((method) => {
    const metrics = result.methods[method] || {};
    const card = makeElement("article", "benchmark-score-card");
    card.append(makeElement("span", "section-kicker", method.toUpperCase()));
    if (!metrics.available) {
      card.append(makeElement("h3", "", "Unavailable"), makeElement("p", "", "Query embeddings or stored repository embeddings are unavailable."));
    } else {
      card.append(makeElement("h3", "", `${Math.round((metrics.recall_at_k || 0) * 100)}% Recall@${result.top_k}`));
      card.append(makeElement("p", "", `Precision ${Math.round((metrics.precision_at_k || 0) * 100)}% · Hit rate ${Math.round((metrics.hit_rate_at_k || 0) * 100)}% · MRR ${(metrics.mrr || 0).toFixed(2)} · ${metrics.scored_answerable_cases} answerable cases`));
    }
    scoreGrid.append(card);
  });
  container.append(scoreGrid);
  const refusal = makeElement("div", "benchmark-refusal-summary", `Hybrid sufficiency gate · ${Math.round(result.hybrid_answerability_accuracy * 100)}% overall answerability accuracy · ${Math.round(result.answerable_sufficient_rate * 100)}% answerable queries had sufficient evidence · ${Math.round(result.unanswerable_refusal_rate * 100)}% of unanswerable queries were correctly refused.`);
  container.append(refusal);
  const quality = result.answer_quality;
  if (quality?.available) {
    container.append(makeElement("h3", "benchmark-case-heading", "Generated answer checks"));
    const qualityGrid = makeElement("div", "benchmark-score-grid");
    [
      ["GOLD CITATION PRECISION", quality.citation_precision],
      ["GOLD CITATION RECALL", quality.citation_recall],
      ["SOURCE-CHECK REJECTION RATE", quality.source_check_rejection_rate],
      ["UNANSWERABLE HALLUCINATION RATE", quality.unanswerable_hallucination_rate],
    ].forEach(([label, value]) => {
      const card = makeElement("article", "benchmark-score-card");
      card.append(makeElement("span", "section-kicker", label));
      card.append(makeElement("h3", "", `${Math.round((value || 0) * 100)}%`));
      qualityGrid.append(card);
    });
    container.append(qualityGrid);
    container.append(makeElement("p", "benchmark-quality-note", quality.note));
  } else if (quality?.reason) {
    container.append(makeElement("p", "benchmark-quality-note", quality.reason));
  }
  const heading = makeElement("h3", "benchmark-case-heading", "Question level results");
  const table = makeElement("div", "benchmark-case-list");
  result.cases.forEach((item) => {
    const row = makeElement("article", "benchmark-case");
    const title = makeElement("b", "", item.question);
    const status = makeElement("span", `benchmark-answerability ${item.answerable ? (item.hybrid_sufficient ? "is-correct" : "is-missed") : (!item.hybrid_sufficient ? "is-correct" : "is-missed")}`, item.answerable ? (item.hybrid_sufficient ? "ANSWERABLE · EVIDENCE FOUND" : "ANSWERABLE · REFUSED") : (item.hybrid_sufficient ? "UNANSWERABLE · SHOULD REFUSE" : "UNANSWERABLE · REFUSED"));
    row.append(title, status);
    ["keyword", "semantic", "hybrid"].forEach((method) => {
      const summary = item.methods[method];
      if (method === "semantic" && !result.methods.semantic.available) {
        row.append(makeElement("p", "benchmark-method-line", "semantic: unavailable (query or repository embeddings missing)"));
        return;
      }
      const line = makeElement("p", "benchmark-method-line", `${method}: ${summary.matched_paths.length ? `matched ${summary.matched_paths.join(", ")}` : "no gold path in top results"} · top ${summary.top_paths.join(", ") || "no results"}`);
      row.append(line);
    });
    if (item.answer_quality) {
      row.append(makeElement(
        "p",
        "benchmark-method-line",
        `answer: ${item.answer_quality.mode} · cited ${item.answer_quality.citation_refs.join(", ") || "no references"} · source-check rejected ${item.answer_quality.rejected_fact_claims} fact claim(s)`,
      ));
    }
    table.append(row);
  });
  container.append(heading, table);
}

document.querySelector("#evaluation-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  const repoId = document.querySelector("#evaluation-repo")?.value;
  const container = document.querySelector("#evaluation-results");
  if (!repoId) return;
  if (button) button.disabled = true;
  if (container) container.textContent = "Running the selected retrieval question set…";
  try {
    const result = await apiRequest("/evaluation/retrieval", {
      method: "POST", body: JSON.stringify({
        repo_id: repoId,
        top_k: 5,
        include_answer_quality: Boolean(document.querySelector("#include-answer-quality")?.checked),
        ...(document.querySelector("#evaluation-dataset")?.value
          ? { benchmark_id: document.querySelector("#evaluation-dataset").value }
          : {}),
      }),
    });
    renderBenchmark(result);
  } catch (error) {
    if (container) container.textContent = error.message;
  } finally {
    if (button) button.disabled = false;
  }
});

async function loadBenchmarkDatasets(repoId, force = false) {
  const select = document.querySelector("#evaluation-dataset");
  if (!select || !repoId || (!force && select.dataset.repoId === repoId)) return;
  const selected = select.value;
  const result = await apiRequest(`/evaluation/datasets?repo_id=${encodeURIComponent(repoId)}`);
  select.replaceChildren();
  const builtin = document.createElement("option");
  builtin.value = "";
  builtin.textContent = "Built-in Codebase Whisperer set · 34 questions";
  select.append(builtin);
  result.datasets.forEach((dataset) => {
    const option = document.createElement("option");
    option.value = dataset.id;
    option.textContent = `${dataset.name} · ${dataset.case_count} questions`;
    select.append(option);
  });
  select.dataset.repoId = repoId;
  if (result.datasets.some((dataset) => dataset.id === selected)) select.value = selected;
}

document.querySelector("#evaluation-repo")?.addEventListener("change", (event) => {
  loadBenchmarkDatasets(event.currentTarget.value, true).catch((error) => setDashboardMessage(error.message, true));
});

document.querySelector("#benchmark-json-file")?.addEventListener("change", async (event) => {
  const file = event.currentTarget.files?.[0];
  if (!file) return;
  try {
    document.querySelector("#benchmark-json").value = await file.text();
  } catch {
    setDashboardMessage("Could not read that JSON file.", true);
  }
});

document.querySelector("#benchmark-import-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const repoId = document.querySelector("#evaluation-repo")?.value;
  if (!repoId) {
    setDashboardMessage("Choose a repository before saving a benchmark set.", true);
    return;
  }
  let dataset;
  try {
    dataset = JSON.parse(document.querySelector("#benchmark-json")?.value || "{}");
  } catch {
    setDashboardMessage("Benchmark content must be valid JSON.", true);
    return;
  }
  if (!dataset || typeof dataset !== "object" || !Array.isArray(dataset.cases)) {
    setDashboardMessage("Include a benchmark name and a cases array.", true);
    return;
  }
  const button = event.currentTarget.querySelector("button[type='submit']");
  if (button) button.disabled = true;
  setDashboardMessage("Saving and validating expected references…");
  try {
    const saved = await apiRequest("/evaluation/datasets", {
      method: "POST",
      body: JSON.stringify({ repo_id: repoId, name: dataset.name, cases: dataset.cases }),
    });
    await loadBenchmarkDatasets(repoId, true);
    const select = document.querySelector("#evaluation-dataset");
    if (select) select.value = saved.id;
    setDashboardMessage(`Saved “${saved.name}” with ${saved.case_count} questions. It is ready to run.`);
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});

function repoOption(repo) {
  const option = document.createElement("option");
  option.value = repo.id;
  option.textContent = repo.full_name;
  return option;
}

async function loadRepositories() {
  const repositories = await apiRequest("/repositories");
  indexedRepositories = repositories;
  const list = document.querySelector("#repo-list");
  const select = document.querySelector("#ask-repo");
  const guideSelect = document.querySelector("#guide-repo");
  const issuesSelect = document.querySelector("#issues-repo");
  const changesSelect = document.querySelector("#changes-repo");
  const actionSelect = document.querySelector("#action-repo");
  const evaluationSelect = document.querySelector("#evaluation-repo");
  const assistantSelect = document.querySelector("#assistant-repo");
  const count = document.querySelector("#repo-count-label");
  if (count) count.textContent = `${repositories.length} indexed`;
  if (select) {
    const previouslySelected = select.value;
    select.replaceChildren();
    if (!repositories.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Index a repository first";
      select.append(option);
    } else {
      repositories.forEach((repo) => select.append(repoOption(repo)));
      if (repositories.some((repo) => repo.id === previouslySelected)) select.value = previouslySelected;
    }
  }
  if (guideSelect) {
    const previouslySelected = guideSelect.value;
    guideSelect.replaceChildren();
    if (!repositories.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Index a repository first";
      guideSelect.append(option);
    } else {
      repositories.forEach((repo) => guideSelect.append(repoOption(repo)));
      if (repositories.some((repo) => repo.id === previouslySelected)) guideSelect.value = previouslySelected;
    }
  }
  if (issuesSelect) {
    const previouslySelected = issuesSelect.value;
    issuesSelect.replaceChildren();
    if (!repositories.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Index a repository first";
      issuesSelect.append(option);
    } else {
      repositories.forEach((repo) => issuesSelect.append(repoOption(repo)));
      if (repositories.some((repo) => repo.id === previouslySelected)) issuesSelect.value = previouslySelected;
    }
  }
  if (changesSelect) {
    const previouslySelected = changesSelect.value;
    changesSelect.replaceChildren();
    if (!repositories.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Index a repository first";
      changesSelect.append(option);
    } else {
      repositories.forEach((repo) => changesSelect.append(repoOption(repo)));
      if (repositories.some((repo) => repo.id === previouslySelected)) changesSelect.value = previouslySelected;
    }
  }
  [actionSelect, evaluationSelect].forEach((target) => {
    if (!target) return;
    const previouslySelected = target.value;
    target.replaceChildren();
    if (!repositories.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Index a repository first";
      target.append(option);
    } else {
      repositories.forEach((repo) => target.append(repoOption(repo)));
      if (repositories.some((repo) => repo.id === previouslySelected)) target.value = previouslySelected;
    }
  });
  if (evaluationSelect?.value) {
    try {
      await loadBenchmarkDatasets(evaluationSelect.value);
    } catch (error) {
      setDashboardMessage(error.message, true);
    }
  }
  if (assistantSelect) {
    const previouslySelected = assistantSelect.value;
    assistantSelect.replaceChildren();
    const prompt = document.createElement("option");
    prompt.value = "";
    prompt.textContent = repositories.length ? "Select an indexed repository" : "No indexed repositories yet";
    assistantSelect.append(prompt);
    repositories.forEach((repo) => assistantSelect.append(repoOption(repo)));
    if (repositories.some((repo) => repo.id === previouslySelected)) assistantSelect.value = previouslySelected;
  }
  if (!list) return;
  list.replaceChildren();
  if (!repositories.length) {
    const empty = document.createElement("div");
    empty.className = "empty-repo-state";
    const icon = document.createElement("span");
    icon.textContent = "⌘";
    const heading = document.createElement("b");
    heading.textContent = "No repository indexed yet";
    const message = document.createElement("p");
    message.textContent = "Paste a public GitHub URL above to create your first searchable snapshot.";
    empty.append(icon, heading, message);
    list.append(empty);
    return;
  }
  repositories.forEach((repo) => {
    const card = document.createElement("article");
    card.className = "repo-card";
    const info = document.createElement("div");
    info.className = "repo-card-info";
    const name = document.createElement("a");
    name.href = repo.url;
    name.target = "_blank";
    name.rel = "noopener noreferrer";
    name.textContent = repo.full_name;
    const meta = document.createElement("p");
    meta.textContent = `${repo.file_count} files · ${repo.chunk_count} source chunks · ${repo.issue_count || 0} open issues · ${repo.commit_count || 0} commits`;
    const syncStatus = document.createElement("span");
    syncStatus.className = `repository-sync-status sync-${repo.sync_status || "current"}`;
    const checkedAt = repo.sync_checked_at ? new Date(repo.sync_checked_at).toLocaleString() : "waiting for first check";
    syncStatus.textContent = `Sync ${String(repo.sync_status || "current").toUpperCase()} · checked ${checkedAt}`;
    info.append(name, meta, syncStatus);
    if (repo.sync_error) info.append(makeElement("small", "repository-sync-error", repo.sync_error));
    const sha = document.createElement("span");
    sha.className = "repo-sha";
    sha.textContent = repo.commit_sha.slice(0, 8);
    card.append(info, sha);
    list.append(card);
  });
}

document.querySelector("#repo-index-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const input = document.querySelector("#repo-url");
  const url = input?.value.trim();
  if (!url) return;
  if (button) button.disabled = true;
  setDashboardMessage("Indexing the repository. Larger projects can take a little while.");
  try {
    const result = await apiRequest("/index", { method: "POST", body: JSON.stringify({ repository_url: url }) });
    await loadRepositories();
    input.value = "";
    const suffix = result.warning ? ` ${result.warning}` : "";
    setDashboardMessage(`Indexed ${result.full_name} at ${result.commit_sha.slice(0, 8)}: ${result.file_count} files, ${result.chunk_count} chunks, ${result.issue_count || 0} open issues, and ${result.commit_count || 0} commits.${suffix}`);
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});

const assistantOverlay = document.querySelector("#assistant-overlay");
const assistantLauncher = document.querySelector("#assistant-launch");
const assistantFeed = document.querySelector("#assistant-feed");
const assistantStatus = document.querySelector("#assistant-status");
const assistantForm = document.querySelector("#assistant-form");
const assistantSubmit = document.querySelector("#assistant-submit");

function openAssistant() {
  if (!assistantOverlay || !dashboardScreen || dashboardScreen.hidden) return;
  assistantOverlay.hidden = false;
  document.body.classList.add("assistant-open");
  window.requestAnimationFrame(() => document.querySelector("#assistant-repo-url")?.focus());
}

function closeAssistant() {
  if (!assistantOverlay || assistantOverlay.hidden) return;
  assistantOverlay.hidden = true;
  document.body.classList.remove("assistant-open");
  assistantLauncher?.focus();
}

function setAssistantStatus(message, isError = false) {
  if (!assistantStatus) return;
  assistantStatus.textContent = message || "";
  assistantStatus.classList.toggle("is-error", Boolean(isError));
}

function addAssistantMessage(role, text) {
  if (!assistantFeed) return null;
  const message = makeElement("article", `assistant-message assistant-message-${role}`);
  message.append(makeElement("span", "assistant-message-label", role === "user" ? "YOU" : "ASSISTANT"));
  message.append(makeElement("p", "", text));
  assistantFeed.append(message);
  assistantFeed.scrollTop = assistantFeed.scrollHeight;
  return message;
}

function getGithubRepositorySlug(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("Enter a valid GitHub repository URL, or choose an indexed repository.");
  }
  if (parsed.protocol !== "https:" || !["github.com", "www.github.com"].includes(parsed.hostname)) {
    throw new Error("Use a public https://github.com/owner/repository URL.");
  }
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (parts.length !== 2) throw new Error("The link must point to a repository, not an issue or a file.");
  const owner = parts[0];
  const name = parts[1].replace(/\.git$/i, "");
  if (!/^[A-Za-z0-9_.-]+$/.test(owner) || !/^[A-Za-z0-9_.-]+$/.test(name)) {
    throw new Error("The repository URL contains an invalid owner or repository name.");
  }
  return `${owner}/${name}`.toLowerCase();
}

function renderAssistantProposal(proposal) {
  const message = document.createElement("article");
  message.className = "assistant-message assistant-message-agent assistant-proposal-message";
  message.append(makeElement("span", "assistant-message-label", "PROPOSAL READY · REVIEW REQUIRED"));
  if (proposal.payload.summary) message.append(makeElement("p", "assistant-proposal-summary", proposal.payload.summary));
  message.append(makeElement("p", "assistant-proposal-meta", `${proposal.repository} · base ${proposal.payload.base_sha?.slice(0, 8) || "unknown"} · branch ${proposal.payload.branch || "pending"}`));

  const validation = proposal.payload.validation;
  if (validation) {
    const validationCard = makeElement("section", `assistant-validation status-${validation.status}`);
    validationCard.append(makeElement("strong", "", `Checks · ${validation.status.replaceAll("_", " ").toUpperCase()}`));
    validationCard.append(makeElement("p", "", validation.message || "No validation summary was returned."));
    (validation.commands || []).forEach((check) => {
      const detail = document.createElement("details");
      detail.className = "assistant-check-detail";
      detail.append(makeElement("summary", "", `${check.label} · ${check.status}${check.exit_code === null || check.exit_code === undefined ? "" : ` · exit ${check.exit_code}`}`));
      if (check.output) detail.append(makeElement("pre", "", check.output));
      validationCard.append(detail);
    });
    message.append(validationCard);
  }

  const changes = proposal.payload.changes || [];
  if (changes.length) {
    message.append(makeElement("p", "assistant-proposal-meta", `Files changed · ${changes.map((change) => change.path).join(" · ")}`));
    changes.forEach((change) => {
      const details = document.createElement("details");
      details.className = "assistant-diff-detail";
      details.append(makeElement("summary", "", change.path));
      details.append(makeElement("pre", "", change.diff || "No diff preview was returned."));
      message.append(details);
    });
  }
  const review = makeElement("button", "button button-dark assistant-review", "Review full proposal & approval");
  review.type = "button";
  review.addEventListener("click", async () => {
    showDashboardView("actions", { refreshActions: false });
    closeAssistant();
    await loadActions();
    document.querySelector("#action-results")?.scrollIntoView({ behavior: "smooth", block: "start" });
    setDashboardMessage("Review the exact diff and sandbox report in Action approvals. GitHub will only be changed if you approve.");
  });
  message.append(review);
  assistantFeed?.append(message);
  if (assistantFeed) assistantFeed.scrollTop = assistantFeed.scrollHeight;
}

assistantLauncher?.addEventListener("click", openAssistant);
document.querySelector("#assistant-close")?.addEventListener("click", closeAssistant);
document.querySelector(".assistant-scrim")?.addEventListener("click", closeAssistant);
document.querySelector("#assistant-repo-url")?.addEventListener("input", (event) => {
  if (event.currentTarget.value) document.querySelector("#assistant-repo").value = "";
});
document.querySelector("#assistant-repo")?.addEventListener("change", (event) => {
  if (event.currentTarget.value) document.querySelector("#assistant-repo-url").value = "";
});
document.addEventListener("keydown", (event) => {
  if (!assistantOverlay || assistantOverlay.hidden) return;
  if (event.key === "Escape") {
    closeAssistant();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = [...(assistantOverlay.querySelector(".assistant-panel")?.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], summary") || [])]
    .filter((element) => element.getClientRects().length > 0);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

assistantForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const task = document.querySelector("#assistant-task")?.value.trim() || "";
  const repositoryUrl = document.querySelector("#assistant-repo-url")?.value.trim() || "";
  const selectedRepoId = document.querySelector("#assistant-repo")?.value || "";
  const issueNumberValue = document.querySelector("#assistant-issue")?.value.trim() || "";
  if (task.length < 3) {
    setAssistantStatus("Describe the bug in at least a few words.", true);
    return;
  }
  if (!repositoryUrl && !selectedRepoId) {
    setAssistantStatus("Paste a GitHub repository URL or choose an indexed repository.", true);
    return;
  }

  let repoId = selectedRepoId;
  let repositoryName = indexedRepositories.find((repo) => repo.id === repoId)?.full_name || "";
  if (repositoryUrl) {
    try {
      const slug = getGithubRepositorySlug(repositoryUrl);
      const existing = indexedRepositories.find((repo) => repo.id.toLowerCase() === slug);
      if (existing) {
        repoId = existing.id;
        repositoryName = existing.full_name;
      } else {
        repoId = "";
        repositoryName = slug;
      }
    } catch (error) {
      setAssistantStatus(error.message, true);
      return;
    }
  }
  const assistantSelect = document.querySelector("#assistant-repo");
  if (assistantSelect && repoId) assistantSelect.value = repoId;

  const firstLine = task.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || task;
  const title = (`Fix: ${firstLine}`).slice(0, 256);
  addAssistantMessage("user", `${task}\nRepository: ${repositoryName || "GitHub repository"}`);
  setAssistantStatus("");
  if (assistantSubmit) assistantSubmit.disabled = true;
  if (repositoryUrl && !repoId) {
    setAssistantStatus(`Indexing ${repositoryName} at its current GitHub commit…`);
  } else {
    setAssistantStatus(`Searching ${repositoryName} for relevant code…`);
  }

  try {
    if (repositoryUrl && !repoId) {
      const indexed = await apiRequest("/index", {
        method: "POST",
        body: JSON.stringify({ repository_url: repositoryUrl }),
      });
      repoId = indexed.repo_id;
      repositoryName = indexed.full_name;
      await loadRepositories();
      const assistantSelect = document.querySelector("#assistant-repo");
      if (assistantSelect) assistantSelect.value = repoId;
      setAssistantStatus(`Indexed ${repositoryName}. Preparing a patch and isolated checks…`);
    } else {
      setAssistantStatus(`Preparing a patch for ${repositoryName} and running isolated checks…`);
    }

    const proposalResult = await apiRequest("/actions/code-fix", {
      method: "POST",
      body: JSON.stringify({
        repo_id: repoId,
        title,
        task,
        ...(issueNumberValue ? { issue_number: Number(issueNumberValue) } : {}),
      }),
    });
    const proposal = proposalResult.proposal;
    await loadActions();
    renderAssistantProposal(proposal);
    document.querySelector("#assistant-task").value = "";
    document.querySelector("#assistant-repo-url").value = "";
    document.querySelector("#assistant-issue").value = "";
    setAssistantStatus("Proposal prepared. Review the diff and check results before approving it.");
  } catch (error) {
    addAssistantMessage("agent", error.message);
    const lastMessage = assistantFeed?.lastElementChild;
    lastMessage?.classList.add("assistant-message-error");
    setAssistantStatus("I couldn’t prepare a safe fix from this request.", true);
  } finally {
    if (assistantSubmit) assistantSubmit.disabled = false;
  }
});

function renderAnswer(result) {
  const container = document.querySelector("#answer-result");
  if (!container) return;
  container.replaceChildren();
  const summary = document.createElement("div");
  summary.className = `answer-result-summary mode-${result.mode}`;
  summary.textContent = result.answer;
  container.append(summary);
  if (result.refusal_reason) {
    const reason = document.createElement("p");
    reason.className = "answer-refusal-reason";
    reason.textContent = result.refusal_reason;
    container.append(reason);
  }
  result.claims.forEach((claim) => {
    const card = document.createElement("article");
    card.className = "answer-claim";
    const status = document.createElement("span");
    status.className = `claim-status ${claim.status}`;
    status.textContent = claim.status === "source_checked" ? "SOURCE CHECKED" : "ASSUMPTION";
    const text = document.createElement("p");
    text.textContent = claim.text;
    const citations = document.createElement("div");
    citations.className = "claim-citations";
    claim.citations.forEach((citation) => {
      const link = document.createElement("a");
      link.href = citation.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = citation.start_line && citation.end_line
        ? `${citation.path} · L${citation.start_line}–${citation.end_line}`
        : `${citation.source_type.toUpperCase()} · ${citation.path}`;
      citations.append(link);
    });
    const note = document.createElement("small");
    note.textContent = claim.verification_note;
    card.append(status, text, citations, note);
    container.append(card);
  });
  if (result.searched_paths?.length) {
    const searched = document.createElement("p");
    searched.className = "searched-paths";
    searched.textContent = `Evidence sources: ${result.searched_paths.join(", ")}`;
    container.append(searched);
  }
}

document.querySelector("#ask-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const repoId = document.querySelector("#ask-repo")?.value;
  const question = document.querySelector("#ask-question")?.value.trim();
  const explanationLanguage = document.querySelector("#ask-language")?.value || "";
  if (!repoId || !question) {
    setDashboardMessage("Index a repository before asking a question.", true);
    return;
  }
  if (button) button.disabled = true;
  setDashboardMessage("Searching the indexed source…");
  try {
    const result = await apiRequest("/ask", {
      method: "POST",
      body: JSON.stringify({ repo_id: repoId, question, ...(explanationLanguage ? { explanation_language: explanationLanguage } : {}) }),
    });
    renderAnswer(result);
    setDashboardMessage("");
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});

function renderIssueMatches(result) {
  const container = document.querySelector("#issue-results");
  const meta = document.querySelector("#issues-meta");
  if (!container || !meta) return;
  container.replaceChildren();
  const synced = result.synced_at ? new Date(result.synced_at).toLocaleString() : "not synced yet";
  meta.textContent = `${result.issue_count} open issues · refreshed ${synced} · source snapshot ${result.commit_sha.slice(0, 8)}`;
  if (result.note && result.recommendations.length) {
    const notice = document.createElement("p");
    notice.className = "issue-notice";
    notice.textContent = result.note;
    container.append(notice);
  }
  if (!result.recommendations.length) {
    const empty = document.createElement("div");
    empty.className = "empty-repo-state issue-empty-state";
    const heading = document.createElement("b");
    heading.textContent = "No matching issues yet";
    const note = document.createElement("p");
    note.textContent = result.note || "Refresh the issue snapshot or try a repository with open issues.";
    empty.append(heading, note);
    container.append(empty);
    return;
  }

  result.recommendations.forEach((issue) => {
    const card = document.createElement("article");
    card.className = "issue-card";
    const header = document.createElement("div");
    header.className = "issue-card-header";
    const titleGroup = document.createElement("div");
    const identifier = document.createElement("span");
    identifier.className = "section-kicker";
    identifier.textContent = `OPEN ISSUE #${issue.number}`;
    const title = document.createElement("h3");
    const issueLink = document.createElement("a");
    issueLink.href = issue.url;
    issueLink.target = "_blank";
    issueLink.rel = "noopener noreferrer";
    issueLink.textContent = issue.title;
    title.append(issueLink);
    titleGroup.append(identifier, title);
    const score = document.createElement("div");
    score.className = "issue-match-score";
    const scoreValue = document.createElement("strong");
    scoreValue.textContent = `${issue.match_score}`;
    const scoreLabel = document.createElement("span");
    scoreLabel.textContent = "MATCH SIGNAL";
    score.append(scoreValue, scoreLabel);
    header.append(titleGroup, score);
    card.append(header);

    if (issue.labels?.length) {
      const labels = document.createElement("div");
      labels.className = "issue-labels";
      issue.labels.forEach((label) => {
        const tag = document.createElement("span");
        tag.textContent = label;
        labels.append(tag);
      });
      card.append(labels);
    }
    const summary = document.createElement("p");
    summary.className = "issue-summary";
    summary.textContent = issue.summary;
    card.append(summary);

    const reasonsHeading = document.createElement("b");
    reasonsHeading.className = "issue-reasons-heading";
    reasonsHeading.textContent = "Why it may fit";
    const reasons = document.createElement("ul");
    reasons.className = "issue-reasons";
    issue.fit_reasons.forEach((reason) => {
      const item = document.createElement("li");
      item.textContent = reason;
      reasons.append(item);
    });
    card.append(reasonsHeading, reasons);

    if (issue.related_files?.length) {
      const filesHeading = document.createElement("b");
      filesHeading.className = "issue-reasons-heading";
      filesHeading.textContent = "Related source";
      const files = document.createElement("div");
      files.className = "claim-citations issue-source-links";
      issue.related_files.forEach((citation) => {
        const link = document.createElement("a");
        link.href = citation.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `${citation.path} · L${citation.start_line}–${citation.end_line}`;
        files.append(link);
      });
      card.append(filesHeading, files);
    }
    const footer = document.createElement("div");
    footer.className = "issue-card-footer";
    const assignment = document.createElement("span");
    assignment.textContent = issue.assignee_count === 0 ? "Currently unassigned" : `${issue.assignee_count} assignee${issue.assignee_count === 1 ? "" : "s"}`;
    const updated = document.createElement("span");
    updated.textContent = issue.updated_at ? `Updated ${new Date(issue.updated_at).toLocaleDateString()}` : "";
    footer.append(assignment, updated);
    card.append(footer);
    container.append(card);
  });
}

async function loadIssueMatches(repoId) {
  const results = await apiRequest(`/issues?repo_id=${encodeURIComponent(repoId)}`);
  renderIssueMatches(results);
}

document.querySelector("#issues-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const repoId = document.querySelector("#issues-repo")?.value;
  const button = event.currentTarget.querySelector("button[type='submit']");
  if (!repoId) {
    setDashboardMessage("Index a repository before matching issues.", true);
    return;
  }
  if (button) button.disabled = true;
  setDashboardMessage("Matching open issues to your profile and repository source…");
  try {
    await loadIssueMatches(repoId);
    setDashboardMessage("");
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});

document.querySelector("#refresh-issues")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const repoId = document.querySelector("#issues-repo")?.value;
  if (!repoId) {
    setDashboardMessage("Index a repository before refreshing its issues.", true);
    return;
  }
  button.disabled = true;
  setDashboardMessage("Refreshing up to 200 open issues from GitHub…");
  try {
    const refreshed = await apiRequest("/issues/refresh", {
      method: "POST",
      body: JSON.stringify({ repo_id: repoId }),
    });
    await loadRepositories();
    await loadIssueMatches(repoId);
    setDashboardMessage(`Refreshed ${refreshed.issue_count} open issues.`);
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});

function renderChanges(result) {
  const container = document.querySelector("#change-result");
  if (!container) return;
  container.replaceChildren();
  const header = document.createElement("div");
  header.className = "change-summary-card";
  const eyebrow = document.createElement("span");
  eyebrow.className = "section-kicker";
  eyebrow.textContent = result.mode === "generated"
    ? "AI CHANGE SUMMARY · CHECK THE DIFF"
    : result.mode === "computed" ? "GITHUB COMMIT SUMMARY" : "RECENT COMMIT HISTORY";
  const title = document.createElement("h3");
  title.textContent = result.repository;
  const summary = document.createElement("p");
  summary.className = "change-summary-text";
  summary.textContent = result.summary;
  const note = document.createElement("small");
  note.className = "change-verification-note";
  note.textContent = result.verification_note;
  header.append(eyebrow, title, summary, note);
  const meta = document.createElement("div");
  meta.className = "change-meta";
  meta.textContent = result.base_commit_sha && result.compared_head_sha
    ? `Compared ${result.base_commit_sha.slice(0, 8)} → ${result.compared_head_sha.slice(0, 8)} · indexed ${result.current_snapshot_sha.slice(0, 8)}${result.last_checked_at ? ` · checked ${new Date(result.last_checked_at).toLocaleString()}` : ""}`
    : `Indexed snapshot ${result.current_snapshot_sha.slice(0, 8)}${result.recent_commits.length ? ` · ${result.recent_commits.length} recent commits loaded` : ""}`;
  container.append(header, meta);

  if (result.comparison_url) {
    const compare = document.createElement("a");
    compare.className = "change-compare-link";
    compare.href = result.comparison_url;
    compare.target = "_blank";
    compare.rel = "noopener noreferrer";
    compare.textContent = `Open GitHub comparison · ${result.commit_total} commits · ${result.file_total} files ↗`;
    container.append(compare);
  }

  if (result.gaps?.length) {
    const gaps = document.createElement("p");
    gaps.className = "change-gaps";
    gaps.textContent = result.gaps.join(" ");
    container.append(gaps);
  }

  if (result.files?.length) {
    const filesHeading = document.createElement("h4");
    filesHeading.className = "change-list-heading";
    filesHeading.textContent = `Changed files (${result.file_total})`;
    const files = document.createElement("div");
    files.className = "changed-file-list";
    result.files.forEach((file) => {
      const details = document.createElement("details");
      details.className = "changed-file-card";
      const summaryLine = document.createElement("summary");
      const fileName = document.createElement("span");
      fileName.textContent = `${file.status} · ${file.path}`;
      const lineCount = document.createElement("small");
      lineCount.textContent = `+${file.additions} / -${file.deletions}`;
      summaryLine.append(fileName, lineCount);
      details.append(summaryLine);
      if (file.html_url) {
        const fileLink = document.createElement("a");
        fileLink.href = file.html_url;
        fileLink.target = "_blank";
        fileLink.rel = "noopener noreferrer";
        fileLink.textContent = "View file on GitHub ↗";
        details.append(fileLink);
      }
      if (file.patch) {
        const patch = document.createElement("pre");
        patch.className = "change-patch";
        patch.textContent = file.patch;
        details.append(patch);
      } else {
        const unavailable = document.createElement("small");
        unavailable.className = "change-no-patch";
        unavailable.textContent = "GitHub did not return a diff excerpt for this file.";
        details.append(unavailable);
      }
      files.append(details);
    });
    container.append(filesHeading, files);
  }

  if (result.recent_commits?.length) {
    const commitsHeading = document.createElement("h4");
    commitsHeading.className = "change-list-heading";
    commitsHeading.textContent = "Recent commit history";
    const commits = document.createElement("div");
    commits.className = "recent-commit-list";
    result.recent_commits.forEach((commit) => {
      const item = document.createElement("article");
      item.className = "recent-commit-card";
      const message = document.createElement("a");
      message.href = commit.html_url;
      message.target = "_blank";
      message.rel = "noopener noreferrer";
      message.textContent = commit.message.split("\n")[0] || "Commit";
      const details = document.createElement("small");
      details.textContent = `${commit.sha.slice(0, 8)} · ${commit.author} · ${commit.committed_at ? new Date(commit.committed_at).toLocaleDateString() : "date unavailable"}`;
      item.append(message, details);
      commits.append(item);
    });
    container.append(commitsHeading, commits);
  }
}

async function loadSavedChanges(repoId) {
  try {
    const result = await apiRequest(`/changes?repo_id=${encodeURIComponent(repoId)}`);
    renderChanges(result);
  } catch (error) {
    setDashboardMessage(error.message, true);
  }
}

document.querySelector("#changes-repo")?.addEventListener("change", (event) => {
  if (event.currentTarget.value) loadSavedChanges(event.currentTarget.value);
});

document.querySelector("#changes-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const repoId = document.querySelector("#changes-repo")?.value;
  const button = event.currentTarget.querySelector("button[type='submit']");
  if (!repoId) {
    setDashboardMessage("Index a repository before refreshing changes.", true);
    return;
  }
  if (button) button.disabled = true;
  setDashboardMessage("Checking GitHub and refreshing the indexed repository snapshot…");
  try {
    const result = await apiRequest("/changes/refresh", {
      method: "POST",
      body: JSON.stringify({ repo_id: repoId }),
    });
    await loadRepositories();
    renderChanges(result);
    setDashboardMessage(result.base_commit_sha === result.compared_head_sha
      ? "Repository checked. The indexed commit is current with GitHub."
      : `Repository refreshed at ${result.current_snapshot_sha.slice(0, 8)} with a linked change summary.`);
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});

function renderGuide(result) {
  const container = document.querySelector("#guide-result");
  if (!container) return;
  container.replaceChildren();

  const header = document.createElement("div");
  header.className = "guide-result-header";
  const eyebrow = document.createElement("span");
  eyebrow.className = "section-kicker";
  eyebrow.textContent = result.mode === "generated" ? "PERSONALIZED FROM REPOSITORY EVIDENCE" : "SOURCE EXCERPTS";
  const title = document.createElement("h3");
  title.textContent = result.title;
  const summary = document.createElement("p");
  summary.textContent = result.summary;
  header.append(eyebrow, title, summary);
  container.append(header);

  result.sections.forEach((section) => {
    const card = document.createElement("article");
    card.className = "guide-section-card";
    const status = document.createElement("span");
    status.className = `claim-status ${section.status}`;
    status.textContent = section.status === "source_checked" ? "SOURCE CHECKED" : "ASSUMPTION";
    const heading = document.createElement("h4");
    heading.textContent = section.title;
    const text = document.createElement("p");
    text.textContent = section.text;
    const citations = document.createElement("div");
    citations.className = "claim-citations";
    section.citations.forEach((citation) => {
      const link = document.createElement("a");
      link.href = citation.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `${citation.path} · L${citation.start_line}–${citation.end_line}`;
      citations.append(link);
    });
    const note = document.createElement("small");
    note.textContent = section.verification_note;
    card.append(status, heading, text, citations, note);
    container.append(card);
  });

  if (result.gaps?.length) {
    const gaps = document.createElement("div");
    gaps.className = "guide-gaps";
    const gapsTitle = document.createElement("b");
    gapsTitle.textContent = "What the repository evidence did not cover";
    const list = document.createElement("ul");
    result.gaps.forEach((gap) => {
      const item = document.createElement("li");
      item.textContent = gap;
      list.append(item);
    });
    gaps.append(gapsTitle, list);
    container.append(gaps);
  }

  if (result.searched_paths?.length) {
    const paths = document.createElement("p");
    paths.className = "searched-paths";
    paths.textContent = `Sources used: ${result.searched_paths.join(", ")}`;
    container.append(paths);
  }
}

document.querySelector("#guide-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const repoId = document.querySelector("#guide-repo")?.value;
  const experienceLevel = document.querySelector("#guide-level")?.value || null;
  const goal = document.querySelector("#guide-goal")?.value.trim() || null;
  if (!repoId) {
    setDashboardMessage("Index a repository before generating an onboarding guide.", true);
    return;
  }
  if (button) button.disabled = true;
  setDashboardMessage("Gathering source evidence and creating your guide…");
  try {
    const result = await apiRequest("/guide", {
      method: "POST",
      body: JSON.stringify({ repo_id: repoId, experience_level: experienceLevel, goal }),
    });
    renderGuide(result);
    setDashboardMessage("");
  } catch (error) {
    setDashboardMessage(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
});

window.addEventListener("hashchange", routeApp);
routeApp();
window.setInterval(() => {
  if (!dashboardUser || dashboardScreen?.hidden) return;
  loadRepositories().catch(() => {});
}, 30000);
