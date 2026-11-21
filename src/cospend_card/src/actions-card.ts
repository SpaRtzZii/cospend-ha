import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";

import { errorMessage, fetchProjects, subscribeChanges } from "./api";
import { translate } from "./i18n";
import type { ActionMode, CospendActionsCardConfig, HassLike, Project } from "./types";
import "./actions-card-editor";
import "./bill-dialog";

const REFRESH_DELAY_MS = 500;
const NOTICE_MS = 6000;

const BUTTONS: Array<{ mode: ActionMode; icon: string; label: string; option: keyof CospendActionsCardConfig }> =
  [
    { mode: "add", icon: "mdi:plus", label: "actions_add", option: "show_add" },
    { mode: "edit", icon: "mdi:pencil-outline", label: "edit", option: "show_edit" },
    { mode: "delete", icon: "mdi:delete-outline", label: "delete", option: "show_delete" },
  ];

type DialogElement = HTMLElement & { hass?: HassLike; project?: Project; mode: ActionMode };

/** Carte à trois boutons : ajouter, modifier ou supprimer une dépense, dans une fenêtre. */
class CospendActionsCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _project: { state: true },
    _failed: { state: true },
    _error: { state: true },
    _notice: { state: true },
  };

  declare hass?: HassLike;
  declare _config?: CospendActionsCardConfig;
  declare _project: Project | null;
  declare _failed: boolean;
  declare _error: string;
  declare _notice: { kind: "ok" | "error"; text: string } | null;

  private _dialog?: DialogElement;
  private _unsubscribe?: () => void;
  private _subscribing = false;
  private _started = false;
  private _refreshTimer?: ReturnType<typeof setTimeout>;
  private _noticeTimer?: ReturnType<typeof setTimeout>;
  private _request = 0;

  constructor() {
    super();
    this._project = null;
    this._failed = false;
    this._error = "";
    this._notice = null;
  }

  static getConfigElement(): HTMLElement {
    return document.createElement("cospend-actions-card-editor");
  }

  static getStubConfig(): Partial<CospendActionsCardConfig> {
    return {};
  }

  setConfig(config: CospendActionsCardConfig): void {
    this._config = { ...config };
    if (this._started) void this._load();
  }

  getCardSize(): number {
    return 2;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 4, rows: 2, min_rows: 2 };
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
    clearTimeout(this._refreshTimer);
    clearTimeout(this._noticeTimer);
    this._closeDialog();
  }

  protected willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass) {
      if (this.isConnected && !this._started) void this._start();
      if (this._dialog) this._dialog.hass = this.hass;
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
      const unsubscribe = await subscribeChanges(this.hass, () => {
        clearTimeout(this._refreshTimer);
        this._refreshTimer = setTimeout(() => void this._load(true), REFRESH_DELAY_MS);
      });
      if (this._started) this._unsubscribe = unsubscribe;
      else unsubscribe();
    } catch {
      // Sans abonnement, la carte fonctionne mais ne suit pas les droits en direct.
    } finally {
      this._subscribing = false;
    }
  }

  // ------------------------------------------------------------------ données

  private get _lang(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this._lang, key, vars);
  }

  private _pickProject(projects: Project[]): Project | null {
    const wanted = this._config?.project;
    if (wanted) {
      return (
        projects.find(
          (p) => p.id === wanted && (!this._config?.entry_id || p.entry_id === this._config.entry_id),
        ) ?? null
      );
    }
    return projects.find((p) => !p.archived) ?? null;
  }

  private async _load(quiet = false): Promise<void> {
    if (!this.hass) return;
    const ticket = ++this._request;
    try {
      const project = this._pickProject(await fetchProjects(this.hass));
      if (ticket !== this._request) return;
      this._project = project;
      this._failed = false;
      this._error = "";
      if (this._dialog) this._dialog.project = project ?? undefined;
    } catch (error) {
      if (ticket !== this._request || quiet) return;
      this._failed = true;
      this._error = errorMessage(error);
    }
  }

  private get _writable(): boolean {
    return this._config?.allow_write !== false && this._project?.can_write === true;
  }

  // ------------------------------------------------------------------ fenêtre

  private _openDialog(mode: ActionMode): void {
    if (!this._project || !this._writable || this._dialog) return;
    const dialog = document.createElement("cospend-bill-dialog") as DialogElement;
    dialog.hass = this.hass;
    dialog.project = this._project;
    dialog.mode = mode;
    dialog.addEventListener("closed", () => this._closeDialog());
    dialog.addEventListener("done", (event) => {
      const detail = (event as CustomEvent<{ text: string; kind: "ok" | "error" }>).detail;
      this._announce(detail.kind, detail.text);
      void this._load(true);
    });
    this._dialog = dialog;
    document.body.append(dialog);
  }

  private _closeDialog(): void {
    this._dialog?.remove();
    this._dialog = undefined;
  }

  private _announce(kind: "ok" | "error", text: string): void {
    this._notice = { kind, text };
    clearTimeout(this._noticeTimer);
    this._noticeTimer = setTimeout(() => (this._notice = null), NOTICE_MS);
  }

  // ------------------------------------------------------------------ rendu

  private _buttons(): TemplateResult {
    const config = this._config!;
    const enabled = this._writable;
    return html`<div class="buttons">
      ${BUTTONS.filter((b) => config[b.option] !== false).map(
        (b) => html`<button
          class="action ${b.mode}"
          ?disabled=${!enabled}
          @click=${() => this._openDialog(b.mode)}
        >
          <ha-icon icon=${b.icon}></ha-icon>
          <span>${this._t(b.label)}</span>
        </button>`,
      )}
    </div>`;
  }

  protected render(): TemplateResult {
    if (!this._config) return html``;
    const project = this._project;
    const title = this._config.title ?? project?.name ?? this._t("card_name");
    return html`
      <ha-card>
        <div class="title">${title}</div>
        ${this._failed && !project
          ? html`<p class="error" role="alert">
              ${this._t("error")} <small>${this._error}</small>
              <button class="retry" @click=${() => void this._load()}>${this._t("retry")}</button>
            </p>`
          : !project
            ? html`<p class="hint">${this._t("no_projects")}</p>`
            : html`
                ${this._buttons()}
                ${!this._writable
                  ? html`<p class="hint">${this._t("read_only")}</p>`
                  : nothing}
              `}
        ${this._notice
          ? html`<p class="notice ${this._notice.kind}" role="status">${this._notice.text}</p>`
          : nothing}
      </ha-card>
    `;
  }

  static styles = css`
    :host {
      display: block;
    }
    ha-card {
      height: 100%;
      box-sizing: border-box;
      padding: 16px;
    }
    .title {
      margin-bottom: 12px;
      font-size: 1.25rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .action {
      flex: 1 1 100px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 12px 8px;
      font: inherit;
      color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 12%, transparent);
      border: none;
      border-radius: 12px;
      cursor: pointer;
    }
    .action.delete {
      color: var(--error-color);
      background: color-mix(in srgb, var(--error-color) 12%, transparent);
    }
    .action:hover:not(:disabled) {
      filter: brightness(0.95);
    }
    .action:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 2px;
    }
    .action:disabled {
      opacity: 0.45;
      cursor: default;
    }
    .hint {
      margin: 8px 0 0;
      color: var(--secondary-text-color);
    }
    .error {
      margin: 0;
      color: var(--error-color);
    }
    .error small {
      display: block;
      color: var(--secondary-text-color);
    }
    .retry {
      margin-top: 8px;
      padding: 6px 14px;
      font: inherit;
      color: var(--primary-color);
      background: none;
      border: 1px solid var(--primary-color);
      border-radius: 18px;
      cursor: pointer;
    }
    .notice {
      margin: 12px 0 0;
      padding: 8px 12px;
      border-radius: 8px;
    }
    .notice.ok {
      color: var(--primary-text-color);
      background: color-mix(in srgb, var(--success-color, #43a047) 18%, transparent);
    }
    .notice.error {
      color: var(--error-color);
      background: color-mix(in srgb, var(--error-color) 12%, transparent);
    }
  `;
}

customElements.define("cospend-actions-card", CospendActionsCard);

window.customCards = window.customCards ?? [];
window.customCards.push({
  type: "cospend-actions-card",
  name: "Cospend — actions",
  description:
    "Trois boutons pour ajouter, modifier ou supprimer une dépense Cospend. / Add, edit or delete an expense.",
  preview: false,
  documentationURL: "https://github.com/SpaRtzZii/cospend-ha",
});
