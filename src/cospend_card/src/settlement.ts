import { LitElement, css, html, nothing } from "lit";
import type { PropertyValues, TemplateResult } from "lit";

import { addBill, errorMessage, fetchSettlement } from "./api";
import { today } from "./bill-payload";
import { formatAmount, initials, memberColor, memberName, readableOn } from "./format";
import { translate } from "./i18n";
import type {
  HassLike,
  Project,
  SettlementPlan,
  SettlementTransaction,
  WriteResult,
} from "./types";

const REIMBURSEMENT_CATEGORY = "-11";

const keyOf = (t: SettlementTransaction) => `${t.from_id}>${t.to_id}`;

/** Plan de remboursement : qui doit combien à qui, avec enregistrement du remboursement. */
class CospendSettlement extends LitElement {
  static properties = {
    hass: { attribute: false },
    project: { attribute: false },
    canWrite: { type: Boolean },
    _plan: { state: true },
    _loading: { state: true },
    _error: { state: true },
    _confirming: { state: true },
    _busy: { state: true },
  };

  declare hass?: HassLike;
  declare project?: Project;
  declare canWrite: boolean;
  declare _plan: SettlementPlan | null;
  declare _loading: boolean;
  declare _error: string;
  declare _confirming: string | null;
  declare _busy: boolean;

  constructor() {
    super();
    this.canWrite = false;
    this._plan = null;
    this._loading = false;
    this._error = "";
    this._confirming = null;
    this._busy = false;
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this.hass?.locale?.language ?? this.hass?.language, key, vars);
  }

  protected willUpdate(changed: PropertyValues): void {
    // Le projet est remplacé à chaque mise à jour des données : le plan suit.
    if (changed.has("project") && this.project && this.hass) void this._load();
  }

  private async _load(): Promise<void> {
    if (!this.hass || !this.project) return;
    this._loading = true;
    try {
      this._plan = await fetchSettlement(this.hass, this.project);
      this._error = "";
    } catch (error) {
      this._error = this._t("settlement_error", { message: errorMessage(error) });
    } finally {
      this._loading = false;
    }
  }

  private _money(value: number): string {
    return formatAmount(
      value,
      this.project?.currency,
      this.hass?.locale?.language ?? this.hass?.language,
    );
  }

  private _isMine(id: number): boolean {
    const me = this.hass?.user?.name?.trim().toLowerCase();
    return !!me && memberName(this.project!, id).trim().toLowerCase() === me;
  }

  private _close = (): void => {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  };

  private async _reimburse(t: SettlementTransaction): Promise<void> {
    if (!this.hass || !this.project || this._busy) return;
    const project = this.project;
    this._busy = true;
    this._error = "";
    try {
      const result: WriteResult = await addBill(this.hass, {
        project: project.id,
        title: `${memberName(project, t.from_id)} → ${memberName(project, t.to_id)}`,
        amount: String(t.amount),
        payer: String(t.from_id),
        owers: [String(t.to_id)],
        split_mode: "even",
        date: today(),
        comment: "",
        category: REIMBURSEMENT_CATEGORY,
      });
      this._confirming = null;
      this.dispatchEvent(
        new CustomEvent("changed", {
          detail: { text: this._t(result?.queued ? "reimbursed_queued" : "reimbursed") },
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

  // ------------------------------------------------------------------ rendu

  protected render(): TemplateResult {
    if (!this.project) return html``;
    const plan = this._plan;
    const rows = [...(plan?.transactions ?? [])].sort(
      (a, b) =>
        Number(this._isMine(b.from_id) || this._isMine(b.to_id)) -
          Number(this._isMine(a.from_id) || this._isMine(a.to_id)) || b.amount - a.amount,
    );
    return html`
      <div class="wrap">
        <div class="top">
          <button class="icon back" aria-label=${this._t("back")} @click=${this._close}>
            <ha-icon icon="mdi:arrow-left"></ha-icon>
          </button>
          <h2>${this._t("settlement_title")}</h2>
        </div>
        ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}
        ${plan?.source === "local" ? html`<p class="note">${this._t("settlement_local")}</p>` : nothing}
        ${plan && plan.pending > 0
          ? html`<p class="note warn">${this._t("settlement_pending", { count: plan.pending })}</p>`
          : nothing}
        ${!plan && this._loading ? html`<p class="hint">${this._t("settlement_loading")}</p>` : nothing}
        ${plan && rows.length === 0
          ? html`<p class="even"><ha-icon icon="mdi:check-circle-outline"></ha-icon>
              ${this._t("settlement_all_even")}</p>`
          : nothing}
        <ul>
          ${rows.map((t) => this._renderRow(t))}
        </ul>
      </div>
    `;
  }

  private _badge(id: number): TemplateResult {
    const member = this.project!.members.find((m) => m.id === id);
    const color = member ? memberColor(member) : "#888888";
    return html`<span class="badge" style="background:${color};color:${readableOn(color)}"
      >${initials(memberName(this.project!, id))}</span
    >`;
  }

  private _renderRow(t: SettlementTransaction): TemplateResult {
    const project = this.project!;
    const from = memberName(project, t.from_id);
    const to = memberName(project, t.to_id);
    const key = keyOf(t);
    const confirming = this._confirming === key;
    return html`<li class="row ${this._isMine(t.from_id) || this._isMine(t.to_id) ? "mine" : ""}">
      <div class="line">
        ${this._badge(t.from_id)}
        <ha-icon class="arrow" icon="mdi:arrow-right"></ha-icon>
        ${this._badge(t.to_id)}
        <span class="grow">
          <span class="text"
            >${this._t("settlement_owes", { from, amount: this._money(t.amount), to })}</span
          >
        </span>
        ${this.canWrite && !confirming
          ? html`<button class="secondary reimburse" @click=${() => (this._confirming = key)}>
              ${this._t("reimburse")}
            </button>`
          : nothing}
      </div>
      ${confirming
        ? html`<div class="confirm">
            <p>
              ${this._t("reimburse_confirm", { from, amount: this._money(t.amount), to })}
            </p>
            <div class="actions">
              <button class="secondary no" @click=${() => (this._confirming = null)}>
                ${this._t("cancel")}
              </button>
              <button class="primary yes" ?disabled=${this._busy} @click=${() => void this._reimburse(t)}>
                ${this._busy ? this._t("saving") : this._t("reimburse_yes")}
              </button>
            </div>
          </div>`
        : nothing}
    </li>`;
  }

  static styles = css`
    :host {
      display: block;
    }
    .wrap {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 4px 16px 12px;
    }
    .top {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    h2 {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    li.row {
      padding: 10px 0;
      border-bottom: 1px solid var(--divider-color);
    }
    li.mine .text {
      font-weight: 500;
    }
    .line {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .grow {
      flex: 1;
      min-width: 0;
    }
    .text {
      color: var(--primary-text-color);
    }
    .arrow {
      color: var(--secondary-text-color);
      --mdc-icon-size: 18px;
    }
    .badge {
      flex: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      font-size: 0.8rem;
      font-weight: 500;
    }
    button {
      font: inherit;
      cursor: pointer;
    }
    button:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 1px;
    }
    button.icon {
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
    button.icon:hover {
      background: var(--secondary-background-color);
    }
    button.primary,
    button.secondary {
      padding: 6px 14px;
      border-radius: 18px;
      border: 1px solid var(--primary-color);
    }
    button.primary {
      color: var(--text-primary-color, #fff);
      background: var(--primary-color);
    }
    button.secondary {
      color: var(--primary-color);
      background: none;
    }
    button:disabled {
      opacity: 0.6;
      cursor: default;
    }
    .confirm {
      margin-top: 8px;
      padding: 10px 12px;
      border-radius: 8px;
      background: var(--secondary-background-color);
    }
    .confirm p {
      margin: 0 0 8px;
      color: var(--primary-text-color);
    }
    .actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
    }
    .note,
    .hint {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .note.warn {
      color: var(--warning-color);
    }
    .even {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0;
      color: var(--success-color);
    }
    .error {
      margin: 0;
      padding: 8px 12px;
      border-radius: 8px;
      color: var(--error-color);
      background: color-mix(in srgb, var(--error-color) 12%, transparent);
    }
  `;
}

customElements.define("cospend-settlement", CospendSettlement);
