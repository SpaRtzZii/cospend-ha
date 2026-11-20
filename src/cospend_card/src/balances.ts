import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";

import { balanceWidth, formatAmount, initials, memberColor, readableOn } from "./format";
import { translate } from "./i18n";
import type { HassLike, Member, Project } from "./types";

/**
 * Soldes des membres. Écran à part (bouton « Soldes » de la carte) ou, avec ``inline``, bloc
 * intégré à la liste des dépenses (option ``inline_balances``).
 */
class CospendBalances extends LitElement {
  static properties = {
    hass: { attribute: false },
    project: { attribute: false },
    inline: { type: Boolean },
  };

  declare hass?: HassLike;
  declare project?: Project;
  declare inline: boolean;

  constructor() {
    super();
    this.inline = false;
  }

  private get _lang(): string | undefined {
    return this.hass?.locale?.language ?? this.hass?.language;
  }

  private _t(key: string): string {
    return translate(this._lang, key);
  }

  private _close = (): void => {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  };

  protected render(): TemplateResult {
    const project = this.project;
    if (!project) return html``;
    const list = html`<ul class="balances">
      ${project.members.map((member) => this._row(project, member))}
    </ul>`;
    if (this.inline) {
      return html`<section>
        <h3>${this._t("balances")}</h3>
        ${list}
      </section>`;
    }
    return html`<div class="wrap">
      <div class="top">
        <button class="icon back" aria-label=${this._t("back")} @click=${this._close}>
          <ha-icon icon="mdi:arrow-left"></ha-icon>
        </button>
        <h2>${this._t("balances")}</h2>
      </div>
      ${list}
      <p class="total">
        <span>${this._t("total_spent")}</span>
        <strong>${formatAmount(project.total_spent, project.currency, this._lang)}</strong>
      </p>
    </div>`;
  }

  private _row(project: Project, member: Member): TemplateResult {
    const width = balanceWidth(member.balance, project.members);
    const tone = member.balance > 0.004 ? "positive" : member.balance < -0.004 ? "negative" : "zero";
    const color = memberColor(member);
    return html`
      <li class=${member.activated ? "" : "inactive"}>
        <span class="avatar" style="background:${color};color:${readableOn(color)}">
          ${initials(member.name)}
        </span>
        <span class="name">
          ${member.name}${member.activated
            ? nothing
            : html` <small>(${this._t("inactive")})</small>`}
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
          ${formatAmount(member.balance, project.currency, this._lang, { sign: true })}
        </span>
      </li>
    `;
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
    h3 {
      margin: 8px 0 4px;
      font-size: 0.8rem;
      font-weight: 500;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--secondary-text-color);
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
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    li {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 6px 0;
    }
    li.inactive {
      opacity: 0.55;
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
    .total {
      display: flex;
      justify-content: space-between;
      margin: 4px 0 0;
      padding-top: 10px;
      border-top: 1px solid var(--divider-color);
      color: var(--secondary-text-color);
    }
    .total strong {
      color: var(--primary-text-color);
      font-weight: 500;
    }
  `;
}

customElements.define("cospend-balances", CospendBalances);
