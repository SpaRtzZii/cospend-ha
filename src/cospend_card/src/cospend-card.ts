import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";

import {
  deleteBill,
  errorMessage,
  fetchBill,
  fetchBills,
  fetchProjects,
  subscribeChanges,
} from "./api";
import {
  balanceWidth,
  categoryBackground,
  categoryView,
  formatAmount,
  formatDate,
  initials,
  memberColor,
  memberName,
  projectKey,
  readableOn,
} from "./format";
import { translate } from "./i18n";
import type {
  BillItem,
  CospendCardConfig,
  HassLike,
  Member,
  Project,
  WriteResult,
} from "./types";
import "./bill-form";
import "./manage";
import "./cospend-card-editor";

const DEFAULT_PAGE_SIZE = 20;
const SEARCH_DELAY_MS = 300;
const REFRESH_DELAY_MS = 500;

class CospendCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _projects: { state: true },
    _selected: { state: true },
    _bills: { state: true },
    _total: { state: true },
    _hasMore: { state: true },
    _loading: { state: true },
    _failed: { state: true },
    _search: { state: true },
    _detail: { state: true },
    _form: { state: true },
    _manage: { state: true },
    _editing: { state: true },
    _confirming: { state: true },
    _busy: { state: true },
    _notice: { state: true },
  };

  declare hass?: HassLike;
  declare _config?: CospendCardConfig;
  declare _projects: Project[] | null;
  declare _selected: string | null;
  declare _bills: BillItem[];
  declare _total: number;
  declare _hasMore: boolean;
  declare _loading: boolean;
  declare _failed: boolean;
  declare _search: string;
  declare _detail: BillItem | null;
  declare _form: boolean;
  declare _manage: boolean;
  declare _editing: boolean;
  declare _confirming: boolean;
  declare _busy: boolean;
  declare _notice: { kind: "ok" | "error"; text: string } | null;

  private _unsubscribe?: () => void;
  private _subscribing = false;
  private _started = false;
  private _searchTimer?: ReturnType<typeof setTimeout>;
  private _refreshTimer?: ReturnType<typeof setTimeout>;
  private _noticeTimer?: ReturnType<typeof setTimeout>;
  private _requestId = 0;

  constructor() {
    super();
    this._projects = null;
    this._selected = null;
    this._bills = [];
    this._total = 0;
    this._hasMore = false;
    this._loading = false;
    this._failed = false;
    this._search = "";
    this._detail = null;
    this._form = false;
    this._manage = false;
    this._editing = false;
    this._confirming = false;
    this._busy = false;
    this._notice = null;
  }

  static getConfigElement(): HTMLElement {
    return document.createElement("cospend-card-editor");
  }

  static getStubConfig(): Partial<CospendCardConfig> {
    return { show_balances: true, show_bills: true, show_search: true };
  }

  setConfig(config: CospendCardConfig): void {
    this._config = { ...config };
    if (this._started) {
      this._selected = null;
      void this._load();
    }
  }

  getCardSize(): number {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 4 };
  }

  // ------------------------------------------------------------------ cycle de vie

  connectedCallback(): void {
    super.connectedCallback();
    if (this.hass) void this._start();
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._unsubscribe?.();
    this._unsubscribe = undefined;
    this._subscribing = false;
    this._started = false;
    clearTimeout(this._searchTimer);
    clearTimeout(this._refreshTimer);
    clearTimeout(this._noticeTimer);
  }

  protected willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass && this.isConnected && !this._started) {
      void this._start();
    }
  }

  private async _start(): Promise<void> {
    if (this._started || !this.hass) return;
    this._started = true;
    await this._load();
    await this._subscribe();
  }

  private async _subscribe(): Promise<void> {
    if (!this.hass || this._unsubscribe || this._subscribing) return;
    this._subscribing = true;
    try {
      const unsubscribe = await subscribeChanges(this.hass, () => this._scheduleRefresh());
      if (this._started) this._unsubscribe = unsubscribe;
      else unsubscribe();
    } catch {
      // Sans abonnement la carte fonctionne, mais ne se met pas à jour toute seule.
    } finally {
      this._subscribing = false;
    }
  }

  private _scheduleRefresh(): void {
    clearTimeout(this._refreshTimer);
    this._refreshTimer = setTimeout(() => void this._refresh(), REFRESH_DELAY_MS);
  }

  // ------------------------------------------------------------------ données

  private get _language(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this._language, key, vars);
  }

  private get _pageSize(): number {
    const size = Number(this._config?.page_size);
    return Number.isFinite(size) && size >= 1 ? Math.min(Math.floor(size), 100) : DEFAULT_PAGE_SIZE;
  }

  private get _project(): Project | undefined {
    return this._projects?.find((project) => projectKey(project) === this._selected);
  }

  /** Projets proposés : celui de la configuration, sinon tous (archivés exclus). */
  private _visibleProjects(projects: Project[]): Project[] {
    const wanted = this._config?.project;
    if (wanted) {
      return projects.filter(
        (project) =>
          project.id === wanted &&
          (!this._config?.entry_id || project.entry_id === this._config.entry_id),
      );
    }
    return projects.filter((project) => !project.archived);
  }

  private async _load(): Promise<void> {
    if (!this.hass) return;
    this._loading = true;
    this._failed = false;
    try {
      const all = await fetchProjects(this.hass);
      const visible = this._visibleProjects(all);
      this._projects = visible;
      if (!visible.some((project) => projectKey(project) === this._selected)) {
        this._selected = visible[0] ? projectKey(visible[0]) : null;
        this._detail = null;
      }
      await this._loadBills(true);
    } catch {
      this._failed = true;
    } finally {
      this._loading = false;
    }
  }

  /** Relit les projets et les dépenses déjà affichées (après un changement signalé). */
  private async _refresh(): Promise<void> {
    if (!this.hass || !this._started) return;
    try {
      const visible = this._visibleProjects(await fetchProjects(this.hass));
      this._projects = visible;
      if (!visible.some((project) => projectKey(project) === this._selected)) {
        this._selected = visible[0] ? projectKey(visible[0]) : null;
        this._detail = null;
      }
      await this._loadBills(true, Math.max(this._bills.length, this._pageSize));
      if (this._detail && this._project) {
        try {
          this._detail = await fetchBill(this.hass, this._project, this._detail.id);
        } catch {
          this._detail = null;
        }
      }
      this._failed = false;
    } catch {
      // On garde l'affichage actuel : la prochaine mise à jour réessaiera.
    }
  }

  private async _loadBills(reset: boolean, limit = this._pageSize): Promise<void> {
    const project = this._project;
    if (!this.hass || !project || this._config?.show_bills === false) {
      this._bills = [];
      this._total = 0;
      this._hasMore = false;
      return;
    }
    const request = ++this._requestId;
    const page = await fetchBills(this.hass, project, {
      offset: reset ? 0 : this._bills.length,
      limit,
      search: this._search,
    });
    if (request !== this._requestId) return; // une réponse plus récente a pris le relais
    this._bills = reset ? page.items : [...this._bills, ...page.items];
    this._total = page.total;
    this._hasMore = page.has_more;
  }

  // ------------------------------------------------------------------ actions

  private _onProject(event: Event): void {
    this._selected = (event.target as HTMLSelectElement).value;
    this._detail = null;
    this._form = false;
    this._search = "";
    void this._guard(() => this._loadBills(true));
  }

  private _onSearch(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this._search = value;
    clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(
      () => void this._guard(() => this._loadBills(true)),
      SEARCH_DELAY_MS,
    );
  }

  private async _more(): Promise<void> {
    await this._guard(() => this._loadBills(false));
  }

  private async _open(item: BillItem): Promise<void> {
    const project = this._project;
    if (!this.hass || !project) return;
    this._confirming = false;
    this._detail = item; // affichage immédiat, complété (parts) par la réponse du serveur
    try {
      this._detail = await fetchBill(this.hass, project, item.id);
    } catch {
      this._detail = item;
    }
  }

  /**
   * Réglages du projet (membres, catégories, modes de paiement, devises).
   *
   * Il faut le niveau gestionnaire (3) sur Nextcloud ; ensuite la roue est visible de tous si
   * l'option ``allow_manage`` est cochée, sinon des seuls administrateurs de Home Assistant.
   */
  private _canManage(project: Project): boolean {
    const allowed = this._config?.allow_manage === true || this.hass?.user?.is_admin === true;
    return allowed && this._canWrite(project) && project.access_level >= 3;
  }

  private _canWrite(project: Project): boolean {
    return this._config?.allow_write !== false && project.can_write;
  }

  private _announce(kind: "ok" | "error", text: string): void {
    this._notice = { kind, text };
    clearTimeout(this._noticeTimer);
    this._noticeTimer = setTimeout(() => (this._notice = null), 6000);
  }

  private async _onSaved(event: CustomEvent<WriteResult & { edited?: boolean }>): Promise<void> {
    this._form = false;
    const edited = Boolean(event.detail?.edited);
    const queued = Boolean(event.detail?.queued);
    this._editing = false;
    this._announce("ok", this._t(`${edited ? "edited" : "saved"}${queued ? "_queued" : ""}`));
    await this._refresh();
  }

  private async _delete(): Promise<void> {
    const project = this._project;
    const item = this._detail;
    if (!this.hass || !project || !item || this._busy) return;
    this._busy = true;
    try {
      const result = await deleteBill(this.hass, project.id, item.ids[0]);
      this._detail = null;
      this._confirming = false;
      this._announce("ok", this._t(result.queued ? "deleted_queued" : "deleted"));
      await this._refresh();
    } catch (error) {
      this._confirming = false;
      this._announce("error", this._t("error_write", { message: errorMessage(error) }));
    } finally {
      this._busy = false;
    }
  }

  private async _guard(action: () => Promise<void>): Promise<void> {
    try {
      this._failed = false;
      await action();
    } catch {
      this._failed = true;
    }
  }

  // ------------------------------------------------------------------ rendu

  protected render(): TemplateResult {
    const title = this._config?.title;
    if (this._failed && !this._projects) return this._shell(title, this._renderError());
    if (!this._projects) return this._shell(title, html`<p class="hint">${this._t("loading")}</p>`);
    if (!this._project) return this._shell(title, html`<p class="hint">${this._t("no_projects")}</p>`);
    const project = this._project;
    const body = this._manage
      ? html`<cospend-manage
          .hass=${this.hass}
          .project=${project}
          @close=${() => (this._manage = false)}
          @changed=${(event: CustomEvent<{ text: string }>) => {
            this._announce("ok", event.detail.text);
            void this._refresh();
          }}
        ></cospend-manage>`
      : this._form
      ? html`<cospend-bill-form
          .hass=${this.hass}
          .project=${project}
          .bill=${this._editing ? (this._detail ?? undefined) : undefined}
          @cancel=${() => {
            this._form = false;
            this._editing = false;
          }}
          @saved=${(event: CustomEvent<WriteResult & { edited?: boolean }>) =>
            void this._onSaved(event)}
        ></cospend-bill-form>`
      : this._detail
      ? this._renderDetail(project, this._detail)
      : html`
          ${project.available ? nothing : html`<p class="banner warn">${this._t("unavailable")}</p>`}
          ${this._failed ? this._renderError() : nothing}
          ${this._config?.show_balances === false ? nothing : this._renderBalances(project)}
          ${this._config?.show_bills === false ? nothing : this._renderBills(project)}
        `;
    return this._shell(title ?? project.name, body, project);
  }

  private _shell(title: string | undefined, body: unknown, project?: Project): TemplateResult {
    const projects = this._projects ?? [];
    const chooser = !this._config?.project && projects.length > 1;
    return html`
      <ha-card>
        <div class="header">
          <div class="title">
            ${title ?? this._t("title_default")}
            ${project?.archived ? html`<span class="chip">${this._t("archived")}</span>` : nothing}
            ${project && !project.can_write && !project.archived
              ? html`<span class="chip">${this._t("read_only")}</span>`
              : nothing}
          </div>
          ${project && project.pending > 0
            ? html`<span class="chip pending" title=${this._t("pending")}>
                <ha-icon icon="mdi:cloud-upload-outline"></ha-icon>
                ${this._t("pending_count", { count: project.pending })}
              </span>`
            : nothing}
          ${project && this._canManage(project) && !this._form && !this._manage
            ? html`<button
                class="gear"
                aria-label=${this._t("manage")}
                title=${this._t("manage")}
                @click=${() => {
                  this._detail = null;
                  this._manage = true;
                }}
              >
                <ha-icon icon="mdi:cog-outline"></ha-icon>
              </button>`
            : nothing}
          ${chooser
            ? html`<select
                class="project-select"
                aria-label=${this._t("project")}
                @change=${this._onProject}
              >
                ${projects.map(
                  (item) => html`<option
                    value=${projectKey(item)}
                    ?selected=${projectKey(item) === this._selected}
                  >
                    ${item.name}
                  </option>`,
                )}
              </select>`
            : nothing}
        </div>
        ${this._notice
          ? html`<p class="banner ${this._notice.kind === "ok" ? "ok" : "error"}" role="status">
              ${this._notice.text}
            </p>`
          : nothing}
        ${body}
      </ha-card>
    `;
  }

  private _renderError(): TemplateResult {
    return html`<div class="banner error">
      ${this._t("error")}
      <button class="link" @click=${() => void this._load()}>${this._t("retry")}</button>
    </div>`;
  }

  private _renderBalances(project: Project): TemplateResult {
    const language = this._language;
    return html`
      <section>
        <h3>${this._t("balances")}</h3>
        <ul class="balances">
          ${project.members.map((member) => this._balanceRow(project, member, language))}
        </ul>
      </section>
    `;
  }

  private _balanceRow(project: Project, member: Member, language: string): TemplateResult {
    const width = balanceWidth(member.balance, project.members);
    const tone = member.balance > 0.004 ? "positive" : member.balance < -0.004 ? "negative" : "zero";
    return html`
      <li class=${member.activated ? "" : "inactive"}>
        ${this._avatar(member)}
        <span class="name">
          ${member.name}${member.activated ? nothing : html` <small>(${this._t("inactive")})</small>`}
        </span>
        <span class="bar" aria-hidden="true">
          <span class="half left">
            ${tone === "negative"
              ? html`<span class="fill negative" style="width:${width}%"></span>`
              : nothing}
          </span>
          <span class="half right">
            ${tone === "positive"
              ? html`<span class="fill positive" style="width:${width}%"></span>`
              : nothing}
          </span>
        </span>
        <span class="amount ${tone}">
          ${formatAmount(member.balance, project.currency, language, { sign: true })}
        </span>
      </li>
    `;
  }

  private _avatar(member: Pick<Member, "name" | "color">): TemplateResult {
    const color = memberColor(member);
    return html`<span class="avatar" style="background:${color};color:${readableOn(color)}">
      ${initials(member.name)}
    </span>`;
  }

  private _renderBills(project: Project): TemplateResult {
    const language = this._language;
    let previousDate = "";
    return html`
      <section>
        <div class="section-head">
          <h3>${this._t("bills")}</h3>
          ${this._canWrite(project)
            ? html`<button
                class="add"
                @click=${() => {
                  this._editing = false;
                  this._form = true;
                }}
              >
                <ha-icon icon="mdi:plus"></ha-icon> ${this._t("add_bill")}
              </button>`
            : nothing}
        </div>
        ${this._config?.show_search === false
          ? nothing
          : html`<input
              class="search"
              type="search"
              .value=${this._search}
              placeholder=${this._t("search_placeholder")}
              aria-label=${this._t("search_label")}
              @input=${this._onSearch}
            />`}
        ${this._bills.length === 0
          ? html`<p class="hint">${this._search ? this._t("empty_search") : this._t("empty")}</p>`
          : html`<ul class="bills">
              ${this._bills.map((item) => {
                const header =
                  item.date !== previousDate
                    ? html`<li class="date-header">${formatDate(item.date, language)}</li>`
                    : nothing;
                previousDate = item.date;
                return html`${header}${this._billRow(project, item, language)}`;
              })}
            </ul>`}
        ${this._hasMore
          ? html`<button class="more" @click=${() => void this._more()}>
              ${this._t("load_more")} (${this._bills.length}/${this._total})
            </button>`
          : nothing}
      </section>
    `;
  }

  private _billRow(project: Project, item: BillItem, language: string): TemplateResult {
    const category = categoryView(project, item.category_id, this._t("reimbursement"));
    const payer = memberName(project, item.payer_id);
    const everyone = item.ower_ids.length === project.members.filter((m) => m.activated).length;
    const owers = everyone
      ? this._t("for_everyone")
      : this._t("for_members", { names: item.ower_ids.map((id) => memberName(project, id)).join(", ") });
    return html`
      <li>
        <button class="row" @click=${() => void this._open(item)}>
          ${this._categoryIcon(category)}
          <span class="main">
            <span class="what">${item.what}</span>
            <span class="sub">${this._t("paid_by", { name: payer })} · ${owers}</span>
          </span>
          <span class="side">
            <span class="total">${formatAmount(item.amount, project.currency, language)}</span>
            ${item.foreign
              ? html`<span class="sub">
                  ${formatAmount(item.foreign.amount, item.foreign.currency, language)}
                </span>`
              : nothing}
            <span class="flags">
              ${item.is_group
                ? html`<ha-icon
                    icon="mdi:call-split"
                    title=${this._t("custom_split")}
                  ></ha-icon>`
                : nothing}
              ${item.repeat !== "n"
                ? html`<ha-icon icon="mdi:repeat" title=${this._t("repeat")}></ha-icon>`
                : nothing}
              ${item.pending
                ? html`<ha-icon icon="mdi:cloud-upload-outline" title=${this._t("pending")}></ha-icon>`
                : nothing}
            </span>
          </span>
        </button>
      </li>
    `;
  }

  /** Pastille de catégorie ; sans catégorie, une icône neutre (Cospend n'en affiche aucune). */
  private _categoryIcon(
    category: ReturnType<typeof categoryView>,
    big = false,
  ): TemplateResult {
    const size = big ? "icon big" : "icon";
    return category && category.icon
      ? html`<span
          class=${size}
          style="background:${categoryBackground(category.color)}"
          title=${category.name}
          aria-hidden="true"
          >${category.icon}</span
        >`
      : html`<span class=${size} aria-hidden="true"
          ><ha-icon icon="mdi:receipt-text-outline"></ha-icon
        ></span>`;
  }

  private _renderDelete(item: BillItem): TemplateResult {
    if (!this._confirming) {
      return html`<div class="detail-actions">
        <button
          class="secondary"
          @click=${() => {
            this._editing = true;
            this._form = true;
          }}
        >
          <ha-icon icon="mdi:pencil-outline"></ha-icon> ${this._t("edit")}
        </button>
        <button class="danger" @click=${() => (this._confirming = true)}>
          <ha-icon icon="mdi:delete-outline"></ha-icon> ${this._t("delete")}
        </button>
      </div>`;
    }
    return html`<div class="confirm" role="alertdialog">
      <p>${this._t(item.is_group ? "confirm_delete_group" : "confirm_delete")}</p>
      <div class="actions">
        <button class="secondary" ?disabled=${this._busy} @click=${() => (this._confirming = false)}>
          ${this._t("cancel")}
        </button>
        <button class="danger solid" ?disabled=${this._busy} @click=${() => void this._delete()}>
          ${this._t("yes_delete")}
        </button>
      </div>
    </div>`;
  }

  private _renderDetail(project: Project, item: BillItem): TemplateResult {
    const language = this._language;
    const category = categoryView(project, item.category_id, this._t("reimbursement"));
    const mode = project.payment_modes.find((p) => p.id === item.payment_mode_id);
    const repeat =
      item.repeat === "n"
        ? ""
        : [
            this._t(`repeat_${item.repeat}`),
            item.repeat_until
              ? this._t("repeat_until", { date: formatDate(item.repeat_until, language) })
              : "",
          ]
            .filter(Boolean)
            .join(" ");
    const payer = project.members.find((m) => m.id === item.payer_id);
    return html`
      <section class="detail">
        <button class="link back" @click=${() => (this._detail = null)}>
          <ha-icon icon="mdi:arrow-left"></ha-icon> ${this._t("back")}
        </button>
        <div class="detail-head">
          ${this._categoryIcon(category, true)}
          <div>
            <h2>${item.what}</h2>
            <div class="total big">${formatAmount(item.amount, project.currency, language)}</div>
            ${item.foreign
              ? html`<div class="sub">
                  ${this._t("original_amount")} :
                  ${formatAmount(item.foreign.amount, item.foreign.currency, language)}
                  (× ${item.foreign.rate})
                </div>`
              : nothing}
          </div>
        </div>
        <dl>
          <dt>${this._t("date")}</dt>
          <dd>${formatDate(item.date, language)}</dd>
          <dt>${this._t("payer")}</dt>
          <dd>${payer ? this._avatar(payer) : nothing} ${memberName(project, item.payer_id)}</dd>
          ${category
            ? html`<dt>${this._t("category")}</dt><dd>${category.icon} ${category.name}</dd>`
            : nothing}
          ${mode ? html`<dt>${this._t("payment_mode")}</dt><dd>${mode.icon} ${mode.name}</dd>` : nothing}
          ${repeat ? html`<dt>${this._t("repeat")}</dt><dd>${repeat}</dd>` : nothing}
          ${item.comment ? html`<dt>${this._t("comment")}</dt><dd>${item.comment}</dd>` : nothing}
        </dl>
        ${item.is_group ? html`<p class="chip">${this._t("custom_split")}</p>` : nothing}
        <h3>${this._t("shares")}</h3>
        <ul class="balances">
          ${(item.shares ?? []).map((share) => {
            const member = project.members.find((m) => m.id === share.member_id);
            return html`<li>
              ${member ? this._avatar(member) : nothing}
              <span class="name">${share.name}</span>
              <span class="amount">${formatAmount(share.amount, project.currency, language)}</span>
            </li>`;
          })}
        </ul>
        ${this._canWrite(project) ? this._renderDelete(item) : nothing}
      </section>
    `;
  }

  static styles = css`
    :host {
      display: block;
    }
    ha-card {
      overflow: hidden;
      padding-bottom: 8px;
    }
    .header {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      padding: 16px 16px 4px;
    }
    .title {
      flex: 1 1 auto;
      font-size: var(--ha-card-header-font-size, 24px);
      font-weight: 400;
      line-height: 1.2;
      color: var(--ha-card-header-color, var(--primary-text-color));
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-left: 6px;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 500;
      vertical-align: middle;
      color: var(--secondary-text-color);
      background: var(--secondary-background-color);
    }
    .chip.pending {
      margin-left: 0;
      color: var(--warning-color, #ffa600);
    }
    .chip ha-icon {
      --mdc-icon-size: 14px;
    }
    .project-select,
    .search {
      box-sizing: border-box;
      font: inherit;
      color: var(--primary-text-color);
      background: var(--card-background-color, var(--ha-card-background));
      border: 1px solid var(--divider-color);
      border-radius: 8px;
      padding: 8px 10px;
    }
    .search {
      width: 100%;
      margin: 0 0 8px;
    }
    .project-select:focus-visible,
    .search:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 1px;
    }
    section {
      padding: 4px 16px 8px;
    }
    h2,
    h3 {
      margin: 12px 0 8px;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    h2 {
      margin: 0;
      font-size: 1.25rem;
    }
    h3 {
      font-size: 0.8rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--secondary-text-color);
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .hint {
      margin: 8px 16px;
      color: var(--secondary-text-color);
    }
    .banner {
      margin: 8px 16px;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 0.9rem;
    }
    .banner.warn {
      color: var(--primary-text-color);
      background: color-mix(in srgb, var(--warning-color, #ffa600) 20%, transparent);
    }
    .banner.ok {
      color: var(--primary-text-color);
      background: color-mix(in srgb, var(--success-color, #43a047) 20%, transparent);
    }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    button.add,
    button.danger,
    button.secondary {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font: inherit;
      padding: 6px 12px;
      border-radius: 8px;
      cursor: pointer;
    }
    button.add {
      color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 12%, transparent);
      border: none;
    }
    button.add ha-icon,
    button.danger ha-icon {
      --mdc-icon-size: 18px;
    }
    .gear {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      padding: 0;
      color: var(--secondary-text-color);
      background: none;
      border: none;
      border-radius: 50%;
      cursor: pointer;
    }
    .gear:hover {
      background: var(--secondary-background-color);
    }
    .detail-actions {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }
    .detail-actions button {
      margin-top: 0 !important;
    }
    button.secondary ha-icon {
      --mdc-icon-size: 18px;
    }
    button.danger {
      margin-top: 12px;
      color: var(--error-color, #db4437);
      background: transparent;
      border: 1px solid var(--error-color, #db4437);
    }
    button.danger.solid {
      margin-top: 0;
      color: #fff;
      background: var(--error-color, #db4437);
    }
    button.secondary {
      color: var(--primary-color);
      background: transparent;
      border: 1px solid var(--divider-color);
    }
    button:disabled {
      opacity: 0.6;
      cursor: default;
    }
    .confirm {
      margin-top: 12px;
      padding: 12px;
      border-radius: 8px;
      background: color-mix(in srgb, var(--error-color, #db4437) 12%, transparent);
    }
    .confirm p {
      margin: 0 0 8px;
      color: var(--primary-text-color);
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
    .banner.error {
      color: var(--primary-text-color);
      background: color-mix(in srgb, var(--error-color, #db4437) 20%, transparent);
    }
    .avatar {
      flex: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      font-size: 12px;
      font-weight: 600;
    }
    dd .avatar {
      width: 22px;
      height: 22px;
      font-size: 10px;
      margin-right: 4px;
      vertical-align: middle;
    }
    .balances li {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 6px 0;
    }
    .balances li.inactive {
      opacity: 0.55;
    }
    .name {
      flex: 0 1 30%;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--primary-text-color);
    }
    .bar {
      flex: 1 1 auto;
      display: flex;
      height: 10px;
      min-width: 40px;
    }
    .half {
      display: flex;
      flex: 1;
      background: var(--secondary-background-color);
    }
    .half.left {
      justify-content: flex-end;
      border-radius: 5px 0 0 5px;
      margin-right: 1px;
    }
    .half.right {
      border-radius: 0 5px 5px 0;
    }
    .fill {
      height: 100%;
    }
    .fill.positive {
      background: var(--success-color, #43a047);
      border-radius: 0 5px 5px 0;
    }
    .fill.negative {
      background: var(--error-color, #db4437);
      border-radius: 5px 0 0 5px;
    }
    .amount {
      flex: none;
      min-width: 84px;
      text-align: right;
      font-variant-numeric: tabular-nums;
      color: var(--primary-text-color);
    }
    .amount.positive {
      color: var(--success-color, #43a047);
    }
    .amount.negative {
      color: var(--error-color, #db4437);
    }
    .date-header {
      padding: 10px 0 2px;
      font-size: 0.75rem;
      font-weight: 500;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--secondary-text-color);
    }
    .row {
      all: unset;
      box-sizing: border-box;
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      padding: 8px 4px;
      border-radius: 8px;
      cursor: pointer;
    }
    .row:hover {
      background: var(--secondary-background-color);
    }
    .row:focus-visible {
      outline: 2px solid var(--primary-color);
    }
    .icon {
      flex: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      font-size: 18px;
      background: var(--secondary-background-color);
    }
    .icon ha-icon {
      --mdc-icon-size: 20px;
      color: var(--secondary-text-color);
    }
    .icon.big {
      width: 48px;
      height: 48px;
      font-size: 24px;
    }
    .main {
      flex: 1 1 auto;
      min-width: 0;
      display: flex;
      flex-direction: column;
    }
    .what {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--primary-text-color);
    }
    .sub {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    .side {
      flex: none;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
    }
    .total {
      font-variant-numeric: tabular-nums;
      color: var(--primary-text-color);
    }
    .total.big {
      font-size: 1.5rem;
    }
    .flags ha-icon {
      --mdc-icon-size: 16px;
      color: var(--secondary-text-color);
    }
    button.link,
    button.more {
      font: inherit;
      color: var(--primary-color);
      background: none;
      border: none;
      cursor: pointer;
    }
    button.more {
      display: block;
      width: 100%;
      margin-top: 8px;
      padding: 8px;
      border-radius: 8px;
      border: 1px solid var(--divider-color);
    }
    button.link {
      padding: 0 4px;
    }
    .back {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin: 8px 0;
    }
    .detail-head {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 8px;
    }
    dl {
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: 6px 16px;
      margin: 12px 0;
    }
    dt {
      color: var(--secondary-text-color);
    }
    dd {
      margin: 0;
      color: var(--primary-text-color);
    }
  `;
}

customElements.define("cospend-card", CospendCard);

declare global {
  interface Window {
    customCards?: Array<{
      type: string;
      name: string;
      description: string;
      preview?: boolean;
      documentationURL?: string;
    }>;
  }
}

window.customCards = window.customCards ?? [];
window.customCards.push({
  type: "cospend-card",
  name: "Cospend",
  description: "Gérez vos dépenses partagées Nextcloud Cospend. / Shared expenses from Nextcloud Cospend.",
  preview: false,
  documentationURL: "https://github.com/SpaRtzZii/cospend-ha",
});
