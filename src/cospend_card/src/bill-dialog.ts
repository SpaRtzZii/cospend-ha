import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";
import { keyed } from "lit/directives/keyed.js";

import { deleteBill, errorMessage, fetchBill, fetchBills } from "./api";
import "./bill-form";
import { formatAmount, formatDate, memberName } from "./format";
import { translate } from "./i18n";
import type { ActionMode, BillItem, HassLike, Project, WriteResult } from "./types";

const LIST_SIZE = 100;
const SEARCH_DELAY_MS = 300;

/**
 * Fenêtre (popup) d'une action sur une dépense : ajouter, modifier ou supprimer.
 *
 * Elle est ajoutée à ``document.body`` par la carte, pour s'afficher au-dessus de tout le
 * tableau de bord quel que soit l'endroit où la carte est posée. Elle émet ``closed`` à la
 * fermeture et ``done`` (avec ``{text, kind}``) quand l'opération est faite.
 */
class CospendBillDialog extends LitElement {
  static properties = {
    hass: { attribute: false },
    project: { attribute: false },
    mode: { attribute: false },
    _items: { state: true },
    _search: { state: true },
    _selected: { state: true },
    _bill: { state: true },
    _loading: { state: true },
    _error: { state: true },
    _confirming: { state: true },
    _busy: { state: true },
  };

  declare hass?: HassLike;
  declare project?: Project;
  declare mode: ActionMode;
  declare _items: BillItem[];
  declare _search: string;
  declare _selected: string;
  declare _bill: BillItem | null;
  declare _loading: boolean;
  declare _error: string;
  declare _confirming: boolean;
  declare _busy: boolean;

  private _timer?: ReturnType<typeof setTimeout>;
  private _ticket = 0;
  private _opener: Element | null = null;

  constructor() {
    super();
    this.mode = "add";
    this._items = [];
    this._search = "";
    this._selected = "";
    this._bill = null;
    this._loading = false;
    this._error = "";
    this._confirming = false;
    this._busy = false;
  }

  connectedCallback(): void {
    super.connectedCallback();
    this._opener = document.activeElement;
    window.addEventListener("keydown", this._onKey);
    if (this.mode !== "add") void this._loadList();
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    window.removeEventListener("keydown", this._onKey);
    clearTimeout(this._timer);
    if (this._opener instanceof HTMLElement) this._opener.focus();
  }

  protected firstUpdated(): void {
    (this.renderRoot.querySelector(".panel") as HTMLElement | null)?.focus();
  }

  private get _lang(): string | undefined {
    return this.hass?.locale?.language ?? this.hass?.language;
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this._lang, key, vars);
  }

  private _onKey = (event: KeyboardEvent): void => {
    if (event.key === "Escape" && !this._busy) this._close();
  };

  private _close(): void {
    this.dispatchEvent(new CustomEvent("closed"));
  }

  private _done(text: string, kind: "ok" | "error" = "ok"): void {
    this.dispatchEvent(new CustomEvent("done", { detail: { text, kind } }));
    this._close();
  }

  // ------------------------------------------------------------------ données

  private async _loadList(): Promise<void> {
    if (!this.hass || !this.project) return;
    const ticket = ++this._ticket;
    this._loading = true;
    try {
      const page = await fetchBills(this.hass, this.project, {
        limit: LIST_SIZE,
        search: this._search,
      });
      if (ticket !== this._ticket) return;
      // Une opération encore en file d'attente n'a pas d'identifiant réel : on ne la propose pas.
      this._items = page.items.filter((item) => !item.pending);
      this._error = "";
      if (this._selected && !this._items.some((item) => String(item.id) === this._selected)) {
        this._selected = "";
        this._bill = null;
      }
    } catch (error) {
      if (ticket !== this._ticket) return;
      this._error = this._t("error_write", { message: errorMessage(error) });
    } finally {
      if (ticket === this._ticket) this._loading = false;
    }
  }

  private _onSearch(event: Event): void {
    this._search = (event.target as HTMLInputElement).value;
    clearTimeout(this._timer);
    this._timer = setTimeout(() => void this._loadList(), SEARCH_DELAY_MS);
  }

  private async _onPick(event: Event): Promise<void> {
    const value = (event.target as HTMLSelectElement).value;
    this._selected = value;
    this._confirming = false;
    this._bill = null;
    this._error = "";
    const item = this._items.find((candidate) => String(candidate.id) === value);
    if (!item || !this.hass || !this.project) return;
    this._bill = item; // affichage immédiat, complété (parts) par la réponse du serveur
    try {
      const full = await fetchBill(this.hass, this.project, item.id);
      if (this._selected === value) this._bill = full;
    } catch {
      // On garde la version de la liste : elle suffit pour modifier ou supprimer.
    }
  }

  private async _delete(): Promise<void> {
    const bill = this._bill;
    if (!this.hass || !this.project || !bill || this._busy) return;
    this._busy = true;
    try {
      const result = await deleteBill(this.hass, this.project.id, bill.ids[0]);
      this._done(this._t(result.queued ? "deleted_queued" : "deleted"));
    } catch (error) {
      this._confirming = false;
      this._error = this._t("error_write", { message: errorMessage(error) });
    } finally {
      this._busy = false;
    }
  }

  private _onSaved(event: CustomEvent<WriteResult & { edited?: boolean }>): void {
    const edited = Boolean(event.detail?.edited);
    const queued = Boolean(event.detail?.queued);
    this._done(this._t(`${edited ? "edited" : "saved"}${queued ? "_queued" : ""}`));
  }

  // ------------------------------------------------------------------ rendu

  private _title(): string {
    return this._t(
      this.mode === "add" ? "add_bill" : this.mode === "edit" ? "actions_edit_title" : "actions_delete_title",
    );
  }

  private _label(item: BillItem): string {
    const amount = formatAmount(item.amount, this.project?.currency, this._lang);
    return `${formatDate(item.date, this._lang)} · ${item.what} · ${amount}`;
  }

  private _picker(): TemplateResult {
    return html`
      <label class="field">
        <span>${this._t("search_label")}</span>
        <input
          type="search"
          name="search"
          .value=${this._search}
          placeholder=${this._t("search_placeholder")}
          @input=${this._onSearch}
        />
      </label>
      <label class="field">
        <span>${this._t("actions_pick")}</span>
        <select name="bill" .value=${this._selected} @change=${(e: Event) => void this._onPick(e)}>
          <option value="">${this._loading ? this._t("loading") : this._t("actions_pick_none")}</option>
          ${this._items.map(
            (item) =>
              html`<option value=${String(item.id)} ?selected=${String(item.id) === this._selected}>
                ${this._label(item)}
              </option>`,
          )}
        </select>
      </label>
      ${!this._loading && this._items.length === 0
        ? html`<p class="hint">${this._t(this._search ? "empty_search" : "empty")}</p>`
        : nothing}
    `;
  }

  private _form(bill: BillItem | undefined): TemplateResult {
    return html`<cospend-bill-form
      .hass=${this.hass}
      .project=${this.project}
      .bill=${bill}
      @cancel=${() => this._close()}
      @saved=${(event: CustomEvent<WriteResult & { edited?: boolean }>) => this._onSaved(event)}
    ></cospend-bill-form>`;
  }

  private _deletePanel(bill: BillItem): TemplateResult {
    const project = this.project!;
    return html`
      <div class="summary">
        <strong>${bill.what}</strong>
        <span>${formatAmount(bill.amount, project.currency, this._lang)}</span>
        <span class="muted">
          ${formatDate(bill.date, this._lang)} ·
          ${this._t("paid_by", { name: memberName(project, bill.payer_id) })}
        </span>
      </div>
      ${this._confirming
        ? html`<div class="confirm" role="alertdialog">
            <p>${this._t(bill.is_group ? "confirm_delete_group" : "confirm_delete")}</p>
            <div class="actions">
              <button
                class="secondary"
                ?disabled=${this._busy}
                @click=${() => (this._confirming = false)}
              >
                ${this._t("cancel")}
              </button>
              <button class="danger solid" ?disabled=${this._busy} @click=${() => void this._delete()}>
                ${this._t("yes_delete")}
              </button>
            </div>
          </div>`
        : html`<div class="actions">
            <button class="secondary" @click=${() => this._close()}>${this._t("cancel")}</button>
            <button class="danger" @click=${() => (this._confirming = true)}>
              ${this._t("delete")}
            </button>
          </div>`}
    `;
  }

  private _content(): TemplateResult {
    if (!this.project) return html``;
    if (this.mode === "add") return this._form(undefined);
    const bill = this._bill;
    return html`
      <div class="picker">${this._picker()}</div>
      ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}
      ${bill
        ? this.mode === "edit"
          ? keyed(bill.id, this._form(bill))
          : this._deletePanel(bill)
        : nothing}
    `;
  }

  protected render(): TemplateResult {
    return html`
      <div class="backdrop" @click=${(e: Event) => e.target === e.currentTarget && !this._busy && this._close()}>
        <div
          class="panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="dlg-title"
          tabindex="-1"
        >
          <div class="head">
            <h2 id="dlg-title">${this._title()}</h2>
            <button class="close" aria-label=${this._t("actions_close")} @click=${() => this._close()}>
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
          ${this._content()}
        </div>
      </div>
    `;
  }

  static styles = css`
    :host {
      position: fixed;
      inset: 0;
      z-index: 9999;
      font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
    }
    .backdrop {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      overflow-y: auto;
      padding: 5vh 12px;
      box-sizing: border-box;
      background: rgba(0, 0, 0, 0.5);
    }
    .panel {
      width: 100%;
      max-width: 560px;
      box-sizing: border-box;
      padding: 8px 4px 12px;
      border-radius: var(--ha-card-border-radius, 12px);
      color: var(--primary-text-color);
      background: var(--card-background-color, #fff);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
      outline: none;
    }
    .head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 12px 0 16px;
    }
    h2 {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 500;
    }
    button {
      font: inherit;
      cursor: pointer;
    }
    button:focus-visible,
    select:focus-visible,
    input:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 1px;
    }
    .close {
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
    }
    .close:hover {
      background: var(--secondary-background-color);
    }
    .picker {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 12px 16px 4px;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    select,
    input[type="search"] {
      box-sizing: border-box;
      width: 100%;
      padding: 8px 10px;
      font: inherit;
      color: var(--primary-text-color);
      background: var(--card-background-color, #fff);
      border: 1px solid var(--divider-color);
      border-radius: 8px;
    }
    .hint {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .error {
      margin: 8px 16px 0;
      color: var(--error-color);
    }
    .summary {
      display: flex;
      flex-direction: column;
      gap: 2px;
      margin: 12px 16px 0;
      padding: 12px;
      border-radius: 8px;
      background: var(--secondary-background-color);
    }
    .muted {
      font-size: 0.85rem;
      color: var(--secondary-text-color);
    }
    .confirm p {
      margin: 12px 16px 0;
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      padding: 12px 16px 4px;
    }
    .actions button {
      padding: 8px 16px;
      border-radius: 20px;
      border: 1px solid var(--primary-color);
      color: var(--primary-color);
      background: none;
    }
    .actions button.danger {
      color: var(--error-color);
      border-color: var(--error-color);
    }
    .actions button.danger.solid {
      color: var(--text-primary-color, #fff);
      background: var(--error-color);
    }
    .actions button:disabled {
      opacity: 0.5;
      cursor: default;
    }
  `;
}

customElements.define("cospend-bill-dialog", CospendBillDialog);
