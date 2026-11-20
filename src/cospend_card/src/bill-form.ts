import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";

import { addBill, errorMessage, updateBill } from "./api";
import { evaluateAmount } from "./amount";
import {
  defaultPayer,
  initialState,
  sharesSum,
  toChanges,
  toCreate,
  today,
  validate,
} from "./bill-payload";
import type { FormState, SplitKind } from "./bill-payload";
import { formatAmount, initials, memberColor, readableOn } from "./format";
import { translate } from "./i18n";
import type { BillItem, HassLike, Member, Project, WriteResult } from "./types";

// Ré-exportés pour les tests et les autres éléments.
export { defaultPayer, today };

const REPEAT_CODES = ["n", "d", "w", "b", "s", "m", "y"];
const SPLITS: SplitKind[] = ["even", "amounts", "percent"];

/** Formulaire de dépense : création, ou modification quand ``bill`` est fourni. */
class CospendBillForm extends LitElement {
  static properties = {
    hass: { attribute: false },
    project: { attribute: false },
    bill: { attribute: false },
    _s: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  declare hass?: HassLike;
  declare project?: Project;
  declare bill?: BillItem;
  declare _s: FormState | null;
  declare _busy: boolean;
  declare _error: string;

  private _base: FormState | null = null;

  constructor() {
    super();
    this._s = null;
    this._busy = false;
    this._error = "";
  }

  protected willUpdate(): void {
    if (!this._s && this.project) {
      this._base = initialState(this.project, this.bill, this.hass?.user?.name);
      this._s = { ...this._base, shares: {} };
    }
  }

  private get _editing(): boolean {
    return this.bill !== undefined;
  }

  /** Répartition personnalisée : montant, participants et devise ne se modifient pas. */
  private get _locked(): boolean {
    return this._editing && Boolean(this.bill?.is_group);
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this.hass?.locale?.language ?? this.hass?.language, key, vars);
  }

  private _set(patch: Partial<FormState>): void {
    if (this._s) this._s = { ...this._s, ...patch };
  }

  private _toggle(id: number): void {
    const s = this._s!;
    this._set({
      owers: s.owers.includes(id) ? s.owers.filter((item) => item !== id) : [...s.owers, id],
    });
  }

  private _cancel(): void {
    this.dispatchEvent(new CustomEvent("cancel", { bubbles: true, composed: true }));
  }

  private _pickCurrency(name: string): void {
    const known = this.project?.currencies.find((currency) => currency.name === name);
    this._set({ currency: name, rate: known ? String(known.exchange_rate) : "" });
  }

  private async _submit(event: Event): Promise<void> {
    event.preventDefault();
    const project = this.project;
    const state = this._s;
    if (!this.hass || !project || !state || this._busy) return;
    const problem = validate(state, this._locked);
    if (problem) {
      this._error = this._t(problem);
      return;
    }
    this._busy = true;
    this._error = "";
    try {
      let result: WriteResult = {};
      if (this._editing && this.bill && this._base) {
        const changes = toChanges(state, this._base, this._locked);
        if (Object.keys(changes).length === 0) {
          this._cancel();
          return;
        }
        result = await updateBill(this.hass, project.id, this.bill.ids[0], changes);
      } else {
        result = await addBill(this.hass, toCreate(project, state));
      }
      this.dispatchEvent(
        new CustomEvent("saved", {
          detail: { ...result, edited: this._editing },
          bubbles: true,
          composed: true,
        }),
      );
    } catch (error) {
      this._error = this._t("error_write", { message: errorMessage(error) });
    } finally {
      this._busy = false;
    }
  }

  protected render(): TemplateResult {
    const project = this.project;
    const s = this._s;
    if (!project || !s) return html``;
    const language = this.hass?.locale?.language ?? this.hass?.language ?? "en";
    const locked = this._locked;
    const active = project.members.filter(
      (member) => member.activated || s.owers.includes(member.id) || member.id === s.payer,
    );
    const total = evaluateAmount(s.amount);
    const rate = Number(s.rate.replace(",", "."));
    const converted =
      s.currency && total !== null && Number.isFinite(rate) && rate > 0
        ? Math.round(total * rate * 100) / 100
        : null;
    const showPreview = total !== null && s.amount.trim() !== String(total);
    return html`
      <form @submit=${this._submit} novalidate>
        <h2>${this._t(this._editing ? "edit_bill" : "new_bill")}</h2>
        ${locked ? html`<p class="info">${this._t("locked_group")}</p>` : nothing}

        <label>
          <span>${this._t("form_title")}</span>
          <input
            type="text"
            required
            autocomplete="off"
            .value=${s.what}
            @input=${(e: Event) => this._set({ what: (e.target as HTMLInputElement).value })}
          />
        </label>

        <label>
          <span>${this._t("form_amount")}</span>
          <input
            type="text"
            inputmode="decimal"
            required
            autocomplete="off"
            ?disabled=${locked}
            placeholder=${this._t("amount_hint")}
            .value=${s.amount}
            @input=${(e: Event) => this._set({ amount: (e.target as HTMLInputElement).value })}
          />
          ${showPreview
            ? html`<small class="preview">
                = ${formatAmount(total!, s.currency ? s.currency : project.currency, language)}
              </small>`
            : nothing}
          ${converted !== null
            ? html`<small class="preview">
                ${this._t("converted", { amount: formatAmount(converted, project.currency, language) })}
              </small>`
            : nothing}
        </label>

        ${project.currencies.length || s.currency
          ? html`<div class="grid">
              <label>
                <span>${this._t("form_currency")}</span>
                <select
                  ?disabled=${locked}
                  @change=${(e: Event) => this._pickCurrency((e.target as HTMLSelectElement).value)}
                >
                  <option value="" ?selected=${s.currency === ""}>
                    ${project.currency || this._t("currency_project")}
                  </option>
                  ${this._currencyOptions(project, s.currency)}
                </select>
              </label>
              ${s.currency
                ? html`<label>
                    <span>${this._t("form_rate")}</span>
                    <input
                      type="text"
                      inputmode="decimal"
                      ?disabled=${locked}
                      .value=${s.rate}
                      @input=${(e: Event) => this._set({ rate: (e.target as HTMLInputElement).value })}
                    />
                  </label>`
                : nothing}
            </div>`
          : nothing}

        <label>
          <span>${this._t("payer")}</span>
          <select @change=${(e: Event) => this._set({ payer: Number((e.target as HTMLSelectElement).value) })}>
            ${active.map(
              (member) =>
                html`<option value=${member.id} ?selected=${member.id === s.payer}>
                  ${member.name}
                </option>`,
            )}
          </select>
        </label>

        <fieldset ?disabled=${locked}>
          <legend>${this._t("form_owers")}</legend>
          ${this._editing
            ? nothing
            : html`<div class="segments" role="radiogroup" aria-label=${this._t("split_mode")}>
                ${SPLITS.map(
                  (kind) =>
                    html`<button
                      type="button"
                      role="radio"
                      aria-checked=${s.split === kind ? "true" : "false"}
                      class="segment ${s.split === kind ? "on" : ""}"
                      @click=${() => this._set({ split: kind })}
                    >
                      ${this._t(`mode_${kind}`)}
                    </button>`,
                )}
              </div>`}
          <div class="chips">${active.map((member) => this._chip(member, s))}</div>
          ${this._splitDetails(project, s, total)}
          ${this.bill?.uneven_weights
            ? html`<small class="warn">${this._t("uneven_warning")}</small>`
            : nothing}
        </fieldset>

        <div class="grid">
          <label>
            <span>${this._t("date")}</span>
            <input
              type="date"
              .value=${s.date}
              @input=${(e: Event) => this._set({ date: (e.target as HTMLInputElement).value })}
            />
          </label>
          <label>
            <span>${this._t("category")}</span>
            <select @change=${(e: Event) => this._set({ category: (e.target as HTMLSelectElement).value })}>
              <option value="">${this._t("no_category")}</option>
              ${s.category === "-11"
                ? html`<option value="-11" selected>💰 ${this._t("reimbursement")}</option>`
                : nothing}
              ${project.categories.map(
                (category) =>
                  html`<option value=${category.id} ?selected=${String(category.id) === s.category}>
                    ${category.icon} ${category.name}
                  </option>`,
              )}
            </select>
          </label>
          ${project.payment_modes.length
            ? html`<label>
                <span>${this._t("payment_mode")}</span>
                <select @change=${(e: Event) => this._set({ mode: (e.target as HTMLSelectElement).value })}>
                  <option value="">${this._t("none")}</option>
                  ${project.payment_modes.map(
                    (mode) =>
                      html`<option value=${mode.id} ?selected=${String(mode.id) === s.mode}>
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
            .value=${s.comment}
            @input=${(e: Event) => this._set({ comment: (e.target as HTMLTextAreaElement).value })}
          ></textarea>
        </label>

        <details ?open=${s.repeat !== "n"}>
          <summary>${this._t("more_options")}</summary>
          <div class="options">
            <label>
              <span>${this._t("repeat")}</span>
              <select @change=${(e: Event) => this._set({ repeat: (e.target as HTMLSelectElement).value })}>
                ${REPEAT_CODES.map(
                  (code) =>
                    html`<option value=${code} ?selected=${s.repeat === code}>
                      ${this._t(`repeat_${code}`)}
                    </option>`,
                )}
              </select>
            </label>
            ${s.repeat !== "n"
              ? html`<div class="grid">
                    <label>
                      <span>${this._t("repeat_every")}</span>
                      <input
                        type="number"
                        min="1"
                        max="999"
                        .value=${s.freq}
                        @input=${(e: Event) => this._set({ freq: (e.target as HTMLInputElement).value })}
                      />
                    </label>
                    <label>
                      <span>${this._t("form_repeat_until")}</span>
                      <input
                        type="date"
                        .value=${s.until}
                        @input=${(e: Event) => this._set({ until: (e.target as HTMLInputElement).value })}
                      />
                    </label>
                  </div>
                  <label class="check">
                    <input
                      type="checkbox"
                      .checked=${s.allActive}
                      @change=${(e: Event) => this._set({ allActive: (e.target as HTMLInputElement).checked })}
                    />
                    <span>${this._t("repeat_all_active")}</span>
                  </label>`
              : nothing}
          </div>
        </details>

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

  private _currencyOptions(project: Project, current: string): TemplateResult[] {
    const names = project.currencies.map((currency) => currency.name);
    if (current && !names.includes(current)) names.push(current); // devise d'origine absente du projet
    return names.map(
      (name) => html`<option value=${name} ?selected=${name === current}>${name}</option>`,
    );
  }

  /** Saisie des parts pour les répartitions en montants ou en pourcentages. */
  private _splitDetails(project: Project, s: FormState, total: number | null): TemplateResult {
    if (this._editing || s.split === "even") {
      return html`<small>${this._t("split_even")}</small>`;
    }
    const sum = Math.round(sharesSum(s) * 100) / 100;
    const ok =
      s.split === "percent" ? Math.abs(sum - 100) < 0.005 : total !== null && Math.abs(sum - total) < 0.005;
    return html`
      <small>${this._t(s.split === "percent" ? "split_percent_hint" : "split_amounts_hint")}</small>
      <div class="shares">
        ${s.owers.map((id) => {
          const member = project.members.find((m) => m.id === id);
          return html`<label class="share">
            <span>${member?.name ?? id}</span>
            <input
              type="text"
              inputmode="decimal"
              autocomplete="off"
              .value=${s.shares[id] ?? ""}
              @input=${(e: Event) =>
                this._set({
                  shares: { ...(this._s?.shares ?? {}), [id]: (e.target as HTMLInputElement).value },
                })}
            />
          </label>`;
        })}
      </div>
      <small class=${ok ? "" : "warn"}>
        ${s.split === "percent"
          ? this._t("percent_total", { sum })
          : this._t("shares_total", { sum, total: total ?? "?" })}
      </small>
    `;
  }

  private _chip(member: Member, s: FormState): TemplateResult {
    const selected = s.owers.includes(member.id);
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
    .segments {
      display: flex;
      gap: 0;
      margin: 4px 0;
    }
    .segment {
      flex: 1;
      font: inherit;
      padding: 7px 8px;
      color: var(--secondary-text-color);
      background: transparent;
      border: 1px solid var(--divider-color);
      cursor: pointer;
    }
    .segment:first-child {
      border-radius: 8px 0 0 8px;
    }
    .segment:last-child {
      border-radius: 0 8px 8px 0;
    }
    .segment + .segment {
      border-left: none;
    }
    .segment.on {
      color: var(--text-primary-color, #fff);
      background: var(--primary-color);
      border-color: var(--primary-color);
    }
    .shares {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
      margin: 4px 0;
    }
    .share span {
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    .warn {
      color: var(--warning-color, #ffa600);
    }
    .info {
      margin: 0;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 0.9rem;
      color: var(--primary-text-color);
      background: color-mix(in srgb, var(--primary-color) 14%, transparent);
    }
    details summary {
      cursor: pointer;
      color: var(--primary-color);
      padding: 4px 0;
    }
    .options {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding-top: 8px;
    }
    label.check {
      flex-direction: row;
      align-items: center;
      gap: 8px;
    }
    label.check input {
      width: auto;
    }
    fieldset:disabled .chip,
    fieldset:disabled button {
      cursor: default;
      opacity: 0.55;
    }
    input:disabled,
    select:disabled {
      opacity: 0.6;
    }
    button:disabled {
      opacity: 0.6;
      cursor: default;
    }
  `;
}

customElements.define("cospend-bill-form", CospendBillForm);
