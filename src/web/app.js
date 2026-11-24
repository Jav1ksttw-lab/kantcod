"use strict";

const kindLabels = {
    omission: "Не указано",
    ambiguity: "Нужно уточнить",
    contradiction: "Противоречие",
};

const fieldLabels = new Map([
    ["job-name", "Название должности"],
    ["duty", "Обязанности"],
    ["requirements", "Требования"],
    ["qualification", "Квалификация"],
    ["requirement.qualification", "Квалификация"],
    ["requirement.education", "Образование"],
    ["salary", "Описание оплаты"],
    ["salary_min", "Минимальная оплата"],
    ["salary_max", "Максимальная оплата"],
    ["schedule", "График"],
    ["shift", "Смены"],
    ["term.text", "Условия"],
    ["conditions", "Условия"],
    ["addresses.address[].location", "Адрес"],
    ["employment", "Занятость"],
]);

const get = (id) => document.getElementById(id);
const number = new Intl.NumberFormat("ru-RU");
const date = new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Kaliningrad",
});
const plural = new Intl.PluralRules("ru-RU");
const state = { report: null, demo: false, selected: null, filter: "all" };
let revision = 0;

function make(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
}

function hasText(value) {
    return typeof value === "string" && value.trim().length > 0;
}

function caption(vacancy) {
    return hasText(vacancy.title) ? vacancy.title : `Вакансия ${vacancy.id}`;
}

function titleCase(value) {
    return value[0].toLocaleUpperCase("ru") + value.slice(1);
}

function formatFindings(count) {
    const word = { one: "замечание", few: "замечания", many: "замечаний", other: "замечаний" };
    return `${number.format(count)} ${word[plural.select(count)]}`;
}

function setNotice(text, warning = false) {
    const notice = get("notice");
    notice.textContent = text;
    notice.hidden = !text;
    notice.classList.toggle("warning", warning);
}

function validReport(report) {
    return Boolean(report && Array.isArray(report.vacancies) && report.vacancies.every((vacancy) =>
        vacancy && (hasText(vacancy.id) || typeof vacancy.id === "number") &&
        Array.isArray(vacancy.findings) && vacancy.findings.every((finding) =>
            finding && ["kind", "topic", "field", "issue", "recommendation"].every((name) => hasText(finding[name]))
        )
    ));
}

function updateOverview(fileName) {
    const { report, demo } = state;
    const findings = report.vacancies.flatMap((vacancy) => vacancy.findings);
    const flagged = report.vacancies.filter((vacancy) => vacancy.findings.length > 0).length;
    get("total").textContent = number.format(report.vacancies.length);
    get("flagged").textContent = number.format(flagged);
    get("finding-count").textContent = number.format(findings.length);
    get("ai-count").textContent = number.format(findings.filter((finding) => finding.origin === "ai").length);
    const label = demo
        ? "Учебный отчёт"
        : (fileName || (["manual", "scheduled"].includes(report.mode) ? "Работа в России" : "Локальный отчёт"));
    const generated = new Date(report.generated_at);
    const model = report.ai?.model;
    const ai = model && model !== "none" ? model : "Проверка по правилам";
    get("metadata").textContent = [
        label,
        Number.isFinite(generated.getTime()) ? `${date.format(generated)} (Калининград)` : "",
        ai,
    ].filter(Boolean).join(" · ");
    const counts = { all: report.vacancies.length, flagged, clear: report.vacancies.length - flagged };
    for (const button of get("filters").querySelectorAll("button")) {
        const names = { all: "Все", flagged: "С замечаниями", clear: "Без замечаний" };
        button.textContent = `${names[button.dataset.filter]} ${number.format(counts[button.dataset.filter])}`;
    }
}

function selectVacancy(vacancy, focusDetails = false) {
    state.selected = vacancy;
    get("vacancies").querySelectorAll("button").forEach((button) => {
        if (button.dataset.id === String(vacancy.id)) button.setAttribute("aria-current", "true");
        else button.removeAttribute("aria-current");
    });
    renderDetails();
    if (focusDetails && window.matchMedia("(max-width: 700px)").matches) {
        get("details").querySelector("h2")?.focus();
    }
}

function renderList() {
    if (!state.report) return;
    const query = get("search").value.trim().toLocaleLowerCase("ru");
    const rows = state.report.vacancies.filter((vacancy) => {
        if (state.filter === "flagged" && !vacancy.findings.length) return false;
        if (state.filter === "clear" && vacancy.findings.length) return false;
        return [vacancy.title, vacancy.employer, vacancy.id]
            .some((value) => String(value ?? "").toLocaleLowerCase("ru").includes(query));
    });
    if (!rows.includes(state.selected)) state.selected = rows[0] ?? null;

    const list = get("vacancies");
    const fragment = document.createDocumentFragment();
    for (const vacancy of rows) {
        const row = make("li");
        const button = make("button", "vacancy");
        button.type = "button";
        button.dataset.id = String(vacancy.id);
        button.setAttribute("aria-controls", "details");
        if (vacancy === state.selected) button.setAttribute("aria-current", "true");
        const label = make("span");
        label.append(make("span", "vacancy-name", caption(vacancy)));
        if (hasText(vacancy.employer)) label.append(make("span", "vacancy-employer", vacancy.employer));
        const count = vacancy.findings.length;
        const badge = make("span", count ? "count" : "count clear", number.format(count));
        badge.setAttribute("aria-hidden", "true");
        button.append(label, badge, make("span", "sr-only", formatFindings(count)));
        button.addEventListener("click", () => selectVacancy(vacancy, true));
        row.append(button);
        fragment.append(row);
    }
    list.replaceChildren(fragment);
    const empty = get("no-results");
    empty.hidden = rows.length > 0;
    empty.textContent = state.report.vacancies.length ? "Вакансии не найдены." : "В отчёте нет вакансий.";
    for (const button of get("filters").querySelectorAll("button")) {
        button.setAttribute("aria-pressed", String(button.dataset.filter === state.filter));
    }
    renderDetails();
}

function portalUrl(value) {
    if (state.demo || !hasText(value)) return null;
    try {
        const url = new URL(value);
        return ["https:", "http:"].includes(url.protocol) ? url.href : null;
    } catch {
        return null;
    }
}

function quote(text, field, index) {
    const block = make("div");
    const label = fieldLabels.get(field) || field || `Поле ${index + 1}`;
    block.append(make("div", "evidence-label", label), make("blockquote", "", text));
    return block;
}

function findingItem(finding) {
    const item = make("li", "finding");
    const head = make("div", "finding-top");
    head.append(make("h3", "", titleCase(finding.topic)));
    if (Object.hasOwn(kindLabels, finding.kind)) {
        head.append(make("span", `kind ${finding.kind}`, kindLabels[finding.kind]));
    }
    if (finding.origin === "ai") head.append(make("span", "kind ai", "Подтвердил ИИ"));
    item.append(head, make("p", "issue", finding.issue));

    if (finding.kind === "contradiction" && Array.isArray(finding.values) && finding.values.length === 2) {
        const evidence = make("div", "evidence conflict");
        finding.values.forEach((value, index) => {
            evidence.append(quote(value, finding.value_fields?.[index] || (index === 0 ? finding.field : ""), index));
        });
        item.append(evidence);
    } else if (hasText(finding.quote)) {
        const evidence = make("div", "evidence");
        evidence.append(quote(finding.quote, finding.field, 0));
        item.append(evidence);
    }

    const next = make("div", "recommendation");
    const text = make("div");
    text.append(make("div", "evidence-label", "Вопрос работодателю"), make("p", "", finding.recommendation));
    const copy = make("button", "button copy", "Копировать");
    copy.type = "button";
    copy.setAttribute("aria-label", `Копировать вопрос · ${finding.topic}`);
    copy.addEventListener("click", async () => {
        try {
            await navigator.clipboard.writeText(finding.recommendation);
            copy.textContent = "Скопировано";
            get("feedback").textContent = "Вопрос скопирован.";
        } catch {
            copy.textContent = "Не скопировано";
            get("feedback").textContent = "Не удалось скопировать вопрос. Выделите его вручную.";
        }
    });
    next.append(text, copy);
    item.append(next);
    return item;
}

function renderDetails() {
    const panel = get("details");
    const vacancy = state.selected;
    if (!vacancy) {
        panel.hidden = true;
        panel.replaceChildren();
        return;
    }

    panel.hidden = false;
    const header = make("div", "detail-header");
    header.append(make("p", "detail-kicker", `ID ${vacancy.id}`));
    const title = make("h2", "", caption(vacancy));
    title.tabIndex = -1;
    header.append(title);
    const meta = make("div", "detail-meta");
    if (hasText(vacancy.employer)) meta.append(make("span", "", vacancy.employer));
    const url = portalUrl(vacancy.url);
    if (url) {
        const link = make("a", "", "Карточка на портале");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        meta.append(link);
    }
    if (meta.childElementCount) header.append(meta);
    panel.replaceChildren(header);

    if (vacancy.findings.length) {
        const list = make("ul", "findings");
        for (const finding of vacancy.findings) list.append(findingItem(finding));
        panel.append(list);
    } else {
        const empty = make("p", "detail-empty");
        empty.append(make("strong", "", "Замечаний нет"), "По результатам этой проверки уточнений не требуется.");
        panel.append(empty);
    }
}

function openReport(report, { demo = false, stale = false, fileName = "" } = {}) {
    if (!validReport(report)) throw new Error("В файле нет списка вакансий с замечаниями.");
    Object.assign(state, { report, demo, selected: null, filter: "all" });
    get("search").value = "";
    updateOverview(fileName);
    renderList();
    get("report").hidden = false;
    get("download").disabled = false;
    const message = stale ? "Последнее обновление завершилось ошибкой. Открыт сохранённый отчёт."
        : Number(report.stats?.ai_errors) > 0 ? "Часть проверок ИИ завершилась ошибкой. Подробности есть в JSON." : "";
    setNotice(message, Boolean(message));
}

async function openSavedReport() {
    const current = ++revision;
    try {
        const response = await fetch("./api/report");
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error);
        if (current === revision) openReport(payload.report, payload);
    } catch {
        if (current === revision) setNotice("Не удалось открыть сохранённый отчёт. Выберите готовый JSON.", true);
    } finally {
        if (current === revision) get("loading").hidden = true;
    }
}

get("search").addEventListener("input", renderList);
get("filters").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    state.filter = button.dataset.filter;
    renderList();
});
get("upload").addEventListener("click", () => get("report-file").click());
get("report-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const current = ++revision;
    try {
        const report = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
        if (current === revision) openReport(report, { fileName: file.name });
    } catch {
        if (current === revision) setNotice("Выберите JSON-отчёт команды run или verify.", true);
    } finally {
        event.target.value = "";
        if (current === revision) get("loading").hidden = true;
    }
});
get("download").addEventListener("click", () => {
    if (!state.report) return;
    const file = new Blob([JSON.stringify(state.report, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(file);
    const link = make("a");
    link.href = url;
    link.download = "vacancy-report.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
});

openSavedReport();
