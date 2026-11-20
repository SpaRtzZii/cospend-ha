import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";

import { addBill, errorMessage } from "./api";
import { evaluateAmount } from "./amount";
import { formatAmount, initials, memberColor, readableOn } from "./format";
import { translate } from "./i18n";
import type { HassLike, Member, Project, WriteResult } from "./types";

/** Date du jour au format ``AAAA-MM-JJ`` dans le fuseau du navigateur. */
export function today(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Payeur proposé : le membre qui porte le nom de l'utilisateur connecté, sinon le premier actif. */
export function defaultPayer(members: Member[], userName: string | undefined): number | null {
  const active = members.filter((member) => member.activated);
  const mine = userName
    ? active.find((member) => member.name.trim().toLowerCase() === userName.trim().toLowerCase())
    : undefined;
  return (mine ?? active[0])?.id ?? null;
}

/** Formulaire de création d'une dépense (répartition égale). */
class CospendBillForm extends LitElement {
  static properties = {
    hass: { attribute: false },
    project: { attribute: false },
    _what: { state: true },
    _amount: { state: true },
    _payer: { state: true },
    _owers: { state: true },
    _date: { state: true },
    _category: { state: true },
    _mode: { state: true },
    _comment: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  declare hass?: HassLike;
  declare project?: Project;
  declare _what: string;
  declare _amount: string;
  declare _payer: number | null;
  declare _owers: number[];
  declare _date: string;
  declare _category: string;
  declare _mode: string;
  declare _comment: string;
  declare _busy: boolean;
  declare _error: string;

  private _initialised = false;

  constructor() {
    super();
    this._what = "";
    this._amount = "";
    this._payer = null;
    this._owers = [];
    this._date = today();
    this._category = "";
    this._mode = "";
    this._comment = "";
    this._busy = false;
    this._error = "";
  }

  protected willUpdate(): void {
    if (!this._initialised && this.project) {
      this._initialised = true;
      this._payer = defaultPayer(this.project.members, this.hass?.user?.name);
      this._owers = this.project.members.filter((m) => m.activated).map((m) => m.id);
    }
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this.hass?.locale?.language ?? this.hass?.language, key, vars);
  }

  private _toggle(id: number): void {
    this._owers = this._owers.includes(id)
      ? this._owers.filter((item) => item !== id)
      : [...this._owers, id];
  }

  private _cancel(): void {
    this.dispatchEvent(new CustomEvent("cancel", { bubbles: true, composed: true }));
  }

  private async _submit(event: Event): Promise<void> {
    event.preventDefault();
    const project = this.project;
    if (!this.hass || !project || this._busy) return;
    if (!this._what.trim() || !this._amount.trim() || this._owers.length === 0 || this._payer === null) {
      this._error = this._t("error_required");
      return;
    }
    const value = evaluateAmount(this._amount);
    if (value !== null && value <= 0) {
      this._error = this._t("error_amount");
      return;
    }
    this._busy = true;
    this._error = "";
    try {
      const result: WriteResult = await addBill(this.hass, {
        project: project.id,
        title: this._what.trim(),
        amount: this._amount.trim(),
        payer: this._payer,
        owers: this._owers,
        date: this._date || today(),
        category: this._category ? Number(this._category) : undefined,
        payment_mode: this._mode ? Number(this._mode) : undefined,
        comment: this._comment.trim(),
      });
      this.dispatchEvent(
        new CustomEvent("saved", { detail: result, bubbles: true, composed: true }),
      );
    } catch (error) {
      this._error = this._t("error_write", { message: errorMessage(error) });
    } finally {
      this._busy = false;
    }
  }

  protected render(): TemplateResult {
    const project = this.project;
    if (!project) return html``;
    const language = this.hass?.locale?.language ?? this.hass?.language ?? "en";
    const active = project.members.filter((member) => member.activated);
    const preview = evaluateAmount(this._amount);
    const showPreview = preview !== null && this._amount.trim() !== String(preview);
    return html`
      <form @submit=${this._submit} novalidate>
        <h2>${this._t("new_bill")}</h2>

        <label>
          <span>${this._t("form_title")}</span>
          <input
            type="text"
            required
            autocomplete="off"
            .value=${this._what}
            @input=${(e: Event) => (this._what = (e.target as HTMLInputElement).value)}
          />
        </label>

        <label>
          <span>${this._t("form_amount")}</span>
          <input
            type="text"
            inputmode="decimal"
            required
            autocomplete="off"
            placeholder=${this._t("amount_hint")}
            .value=${this._amount}
            @input=${(e: Event) => (this._amount = (e.target as HTMLInputElement).value)}
          />
          ${showPreview
            ? html`<small class="preview">= ${formatAmount(preview!, project.currency, language)}</small>`
            : nothing}
        </label>

        <label>
          <span>${this._t("payer")}</span>
          <select
            @change=${(e: Event) => (this._payer = Number((e.target as HTMLSelectElement).value))}
          >
            ${active.map(
              (member) =>
                html`<option value=${member.id} ?selected=${member.id === this._payer}>
                  ${member.name}
                </option>`,
            )}
          </select>
        </label>

        <fieldset>
          <legend>${this._t("form_owers")}</legend>
          <div class="chips">
            ${active.map((member) => this._chip(member))}
          </div>
          <small>${this._t("split_even")}</small>
        </fieldset>

        <div class="grid">
          <label>
            <span>${this._t("date")}</span>
            <input
              type="date"
              .value=${this._date}
              @input=${(e: Event) => (this._date = (e.target as HTMLInputElement).value)}
            />
          </label>
          <label>
            <span>${this._t("category")}</span>
            <select
              @change=${(e: Event) => (this._category = (e.target as HTMLSelectElement).value)}
            >
              <option value="">${this._t("no_category")}</option>
              ${project.categories.map(
                (category) =>
                  html`<option value=${category.id} ?selected=${String(category.id) === this._category}>
                    ${category.icon} ${category.name}
                  </option>`,
              )}
            </select>
          </label>
          ${project.payment_modes.length
            ? html`<label>
                <span>${this._t("payment_mode")}</span>
                <select
                  @change=${(e: Event) => (this._mode = (e.target as HTMLSelectElement).value)}
                >
                  <option value="">${this._t("none")}</option>
                  ${project.payment_modes.map(
                    (mode) =>
                      html`<option value=${mode.id} ?selected=${String(mode.id) === this._mode}>
                        ${mode.icon} ${mode.name}
                      </option>`,
                  )}
                </select>
              </label>`
            : nothing}
        </div>

        <label>
          <span>${this._t("comment")}</span>
          <textarea
            rows="2"
            .value=${this._comment}
            @input=${(e: Event) => (this._comment = (e.target as HTMLTextAreaElement).value)}
          ></textarea>
        </label>

        ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}

        <div class="actions">
          <button type="button" class="secondary" @click=${this._cancel} ?disabled=${this._busy}>
            ${this._t("cancel")}
          </button>
          <button type="submit" class="primary" ?disabled=${this._busy}>
            ${this._busy ? this._t("saving") : this._t("save")}
          </button>
        </div>
      </form>
    `;
  }

  private _chip(member: Member): TemplateResult {
    const selected = this._owers.includes(member.id);
    const color = memberColor(member);
    return html`<button
      type="button"
      class="chip ${selected ? "on" : ""}"
      aria-pressed=${selected ? "true" : "false"}
      @click=${() => this._toggle(member.id)}
    >
      <span class="dot" style="background:${color};color:${readableOn(color)}">
        ${initials(member.name)}
      </span>
      ${member.name}
    </button>`;
  }

  static styles = css`
    :host {
      display: block;
    }
    form {
      display: flex;
      flex-direction: column;
      gap: 14px;
      padding: 4px 16px 12px;
    }
    h2 {
      margin: 8px 0 0;
      font-size: 1.25rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    label,
    fieldset {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin: 0;
      padding: 0;
      border: none;
      min-width: 0;
    }
    label > span,
    legend {
      padding: 0;
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    input,
    select,
    textarea {
      box-sizing: border-box;
      width: 100%;
      font: inherit;
      color: var(--primary-text-color);
      background: var(--card-background-color, var(--ha-card-background));
      border: 1px solid var(--divider-color);
      border-radius: 8px;
      padding: 9px 10px;
    }
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible,
    button:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 1px;
    }
    textarea {
      resize: vertical;
    }
    small {
      color: var(--secondary-text-color);
    }
    .preview {
      color: var(--primary-text-color);
      font-variant-numeric: tabular-nums;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 4px 0;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font: inherit;
      padding: 4px 12px 4px 4px;
      color: var(--secondary-text-color);
      background: transparent;
      border: 1px solid var(--divider-color);
      border-radius: 999px;
      cursor: pointer;
      opacity: 0.7;
    }
    .chip.on {
      color: var(--primary-text-color);
      border-color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 14%, transparent);
      opacity: 1;
    }
    .dot {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      font-size: 10px;
      font-weight: 600;
    }
    .error {
      margin: 0;
      padding: 8px 12px;
      border-radius: 8px;
      color: var(--primary-text-color);
      background: color-mix(in srgb, var(--error-color, #db4437) 20%, transparent);
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }
    button.primary,
    button.secondary {
      font: inherit;
      font-weight: 500;
      padding: 9px 18px;
      border-radius: 8px;
      cursor: pointer;
    }
    button.primary {
      color: var(--text-primary-color, #fff);
      background: var(--primary-color);
      border: 1px solid var(--primary-color);
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
  `;
}

customElements.define("cospend-bill-form", CospendBillForm);
