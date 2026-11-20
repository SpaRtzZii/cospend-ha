import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";

import { errorMessage, manageProject } from "./api";
import { initials, memberColor, readableOn } from "./format";
import { translate } from "./i18n";
import { KINDS, emptyState, stateOf, toDelete, toService, validateItem } from "./manage-payload";
import type { Item, ItemState, Kind } from "./manage-payload";
import type { Category, Currency, HassLike, Member, PaymentMode, Project } from "./types";

const FALLBACK_COLOR = "#888888";

/** Gestion du projet : membres, catégories, modes de paiement et devises. */
class CospendManage extends LitElement {
  static properties = {
    hass: { attribute: false },
    project: { attribute: false },
    _tab: { state: true },
    _item: { state: true },
    _draft: { state: true },
    _deleting: { state: true },
    _busy: { state: true },
    _error: { state: true },
  };

  declare hass?: HassLike;
  declare project?: Project;
  declare _tab: Kind;
  /** Élément en cours de modification (``id`` null : création) ; ``null`` quand on est sur la liste. */
  declare _item: { id: number | null } | null;
  declare _draft: ItemState;
  declare _deleting: number | null;
  declare _busy: boolean;
  declare _error: string;

  constructor() {
    super();
    this._tab = "members";
    this._item = null;
    this._draft = emptyState("members");
    this._deleting = null;
    this._busy = false;
    this._error = "";
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this.hass?.locale?.language ?? this.hass?.language, key, vars);
  }

  private _items(kind: Kind): Item[] {
    const project = this.project!;
    return project[kind] as Item[];
  }

  private _find(id: number): Item | undefined {
    return this._items(this._tab).find((item) => item.id === id);
  }

  private _switch(kind: Kind): void {
    this._tab = kind;
    this._item = null;
    this._deleting = null;
    this._error = "";
  }

  private _open(id: number | null): void {
    const item = id === null ? undefined : this._find(id);
    this._draft = item ? stateOf(this._tab, item) : emptyState(this._tab);
    this._item = { id };
    this._deleting = null;
    this._error = "";
  }

  private _set(patch: Partial<ItemState>): void {
    this._draft = { ...this._draft, ...patch };
  }

  private async _run(
    spec: { service: string; data: Record<string, unknown> },
    done: string,
  ): Promise<void> {
    if (!this.hass) return;
    this._busy = true;
    this._error = "";
    try {
      await manageProject(this.hass, spec.service, spec.data);
      this._item = null;
      this._deleting = null;
      this.dispatchEvent(
        new CustomEvent("changed", { detail: { text: this._t(done) }, bubbles: true, composed: true }),
      );
    } catch (error) {
      this._error = this._t("error_write", { message: errorMessage(error) });
    } finally {
      this._busy = false;
    }
  }

  private async _save(event: Event): Promise<void> {
    event.preventDefault();
    const project = this.project!;
    const problem = validateItem(this._tab, this._draft);
    if (problem) {
      this._error = this._t(problem);
      return;
    }
    const id = this._item?.id ?? null;
    const base = id === null ? undefined : { id, state: stateOf(this._tab, this._find(id)!) };
    const spec = toService(this._tab, project.id, this._draft, base);
    if (!spec) {
      this._item = null; // rien n'a changé
      return;
    }
    await this._run(spec, id === null ? "item_added" : "item_updated");
  }

  // ------------------------------------------------------------------ rendu

  protected render(): TemplateResult {
    if (!this.project) return html``;
    return html`
      <div class="wrap">
        <div class="top">
          <button class="icon" aria-label=${this._t("back")} @click=${this._close}>
            <ha-icon icon="mdi:arrow-left"></ha-icon>
          </button>
          <h2>${this._t("manage_title")}</h2>
        </div>
        <div class="tabs" role="tablist">
          ${KINDS.map(
            (kind) => html`<button
              role="tab"
              aria-selected=${kind === this._tab ? "true" : "false"}
              class="tab ${kind === this._tab ? "on" : ""}"
              @click=${() => this._switch(kind)}
            >
              ${this._t(`tab_${kind}`)}
            </button>`,
          )}
        </div>
        ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}
        ${this._item ? this._renderForm() : this._renderList()}
        <small class="foot">${this._t("manage_online")}</small>
      </div>
    `;
  }

  private _close = (): void => {
    this.dispatchEvent(new CustomEvent("close", { bubbles: true, composed: true }));
  };

  private _renderList(): TemplateResult {
    const items = this._items(this._tab);
    return html`
      <ul>
        ${items.length === 0 ? html`<li class="empty">${this._t("no_items")}</li>` : nothing}
        ${items.map((item) =>
          this._deleting === item.id ? this._renderConfirm(item) : this._renderRow(item),
        )}
      </ul>
      <button class="primary add" @click=${() => this._open(null)}>
        <ha-icon icon="mdi:plus"></ha-icon> ${this._t(`add_${this._tab}`)}
      </button>
    `;
  }

  private _badge(item: Item): TemplateResult {
    if (this._tab === "members") {
      const member = item as Member;
      const color = memberColor(member);
      return html`<span class="badge" style="background:${color};color:${readableOn(color)}"
        >${initials(member.name)}</span
      >`;
    }
    if (this._tab === "currencies") {
      return html`<span class="badge plain"><ha-icon icon="mdi:cash-multiple"></ha-icon></span>`;
    }
    const labelled = item as Category | PaymentMode;
    const color = labelled.color || FALLBACK_COLOR;
    return html`<span class="badge" style="background:${color}33;color:var(--primary-text-color)"
      >${labelled.icon || labelled.name.slice(0, 1).toUpperCase()}</span
    >`;
  }

  private _meta(item: Item): string {
    if (this._tab === "members") {
      const member = item as Member;
      const parts = [this._t("item_weight_value", { weight: member.weight })];
      if (!member.activated) parts.push(this._t("item_inactive"));
      return parts.join(" · ");
    }
    if (this._tab === "currencies") {
      return `× ${(item as Currency).exchange_rate}`;
    }
    return "";
  }

  private _renderRow(item: Item): TemplateResult {
    const inactive = this._tab === "members" && !(item as Member).activated;
    return html`<li class="row ${inactive ? "dim" : ""}">
      ${this._badge(item)}
      <span class="grow">
        <span class="name">${item.name}</span>
        ${this._meta(item) ? html`<small>${this._meta(item)}</small>` : nothing}
      </span>
      <button class="icon edit" aria-label=${this._t("edit")} @click=${() => this._open(item.id)}>
        <ha-icon icon="mdi:pencil-outline"></ha-icon>
      </button>
      <button
        class="icon remove"
        aria-label=${this._t("delete")}
        @click=${() => {
          this._deleting = item.id;
          this._error = "";
        }}
      >
        <ha-icon icon="mdi:delete-outline"></ha-icon>
      </button>
    </li>`;
  }

  private _renderConfirm(item: Item): TemplateResult {
    return html`<li class="confirm">
      <p>${this._t(`confirm_delete_${this._tab}`, { name: item.name })}</p>
      <div class="actions">
        <button class="secondary" @click=${() => (this._deleting = null)}>
          ${this._t("cancel")}
        </button>
        <button
          class="danger yes"
          ?disabled=${this._busy}
          @click=${() =>
            void this._run(toDelete(this._tab, this.project!.id, item.id), "item_deleted")}
        >
          ${this._t("yes_delete")}
        </button>
      </div>
    </li>`;
  }

  private _renderForm(): TemplateResult {
    const d = this._draft;
    const kind = this._tab;
    const creating = this._item?.id === null;
    return html`
      <form @submit=${this._save} novalidate>
        <h3>${this._t(`${creating ? "add" : "edit"}_${kind}`)}</h3>
        <label>
          <span>${this._t(kind === "currencies" ? "item_code" : "item_name")}</span>
          <input
            type="text"
            name="name"
            autocomplete="off"
            .value=${d.name}
            @input=${(e: Event) => this._set({ name: (e.target as HTMLInputElement).value })}
          />
        </label>
        ${kind === "members"
          ? html`<label>
                <span>${this._t("item_weight")}</span>
                <input
                  type="text"
                  name="weight"
                  inputmode="decimal"
                  .value=${d.weight}
                  @input=${(e: Event) => this._set({ weight: (e.target as HTMLInputElement).value })}
                />
              </label>
              <label class="check">
                <input
                  type="checkbox"
                  name="active"
                  .checked=${d.active}
                  @change=${(e: Event) => this._set({ active: (e.target as HTMLInputElement).checked })}
                />
                <span>${this._t("item_active")}</span>
              </label>`
          : nothing}
        ${kind === "categories" || kind === "payment_modes"
          ? html`<label>
              <span>${this._t("item_icon")}</span>
              <input
                type="text"
                name="icon"
                maxlength="16"
                autocomplete="off"
                .value=${d.icon}
                @input=${(e: Event) => this._set({ icon: (e.target as HTMLInputElement).value })}
              />
            </label>`
          : nothing}
        ${kind === "currencies"
          ? html`<label>
              <span>${this._t("item_rate")}</span>
              <input
                type="text"
                name="rate"
                inputmode="decimal"
                .value=${d.rate}
                @input=${(e: Event) => this._set({ rate: (e.target as HTMLInputElement).value })}
              />
              <small
                >${this._t("item_rate_hint", { currency: this.project!.currency ?? "" })}</small
              >
            </label>`
          : html`<label>
              <span>${this._t("item_color")}</span>
              <input
                type="color"
                name="color"
                .value=${d.color || FALLBACK_COLOR}
                @input=${(e: Event) => this._set({ color: (e.target as HTMLInputElement).value })}
              />
            </label>`}
        <div class="actions">
          <button type="button" class="secondary" @click=${() => (this._item = null)}>
            ${this._t("cancel")}
          </button>
          <button type="submit" class="primary" ?disabled=${this._busy}>
            ${this._busy ? this._t("saving") : this._t("save")}
          </button>
        </div>
      </form>
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
    h2,
    h3 {
      margin: 0;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    h2 {
      font-size: 1.25rem;
    }
    h3 {
      font-size: 1.05rem;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .tab {
      font: inherit;
      cursor: pointer;
      color: var(--primary-text-color);
      background: var(--secondary-background-color);
      border: 1px solid var(--divider-color);
      border-radius: 16px;
      padding: 5px 12px;
    }
    .tab.on {
      color: var(--text-primary-color, #fff);
      background: var(--primary-color);
      border-color: var(--primary-color);
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
    }
    li {
      padding: 8px 0;
      border-bottom: 1px solid var(--divider-color);
    }
    li.row {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    li.dim .name {
      color: var(--secondary-text-color);
    }
    li.empty {
      color: var(--secondary-text-color);
      border: none;
    }
    .grow {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
    }
    .name {
      color: var(--primary-text-color);
      overflow: hidden;
      text-overflow: ellipsis;
    }
    small,
    .foot {
      color: var(--secondary-text-color);
    }
    .badge {
      flex: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 50%;
      font-size: 0.85rem;
      font-weight: 500;
    }
    .badge.plain {
      background: var(--secondary-background-color);
      color: var(--secondary-text-color);
    }
    button {
      font: inherit;
      cursor: pointer;
    }
    button:focus-visible,
    input:focus-visible {
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
    button.secondary,
    button.danger {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 8px 16px;
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
    button.danger {
      color: var(--text-primary-color, #fff);
      background: var(--error-color);
      border-color: var(--error-color);
    }
    button:disabled {
      opacity: 0.6;
      cursor: default;
    }
    .add {
      align-self: flex-start;
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
    form {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    label {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    label > span {
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    label.check {
      flex-direction: row;
      align-items: center;
      gap: 8px;
    }
    label.check > span {
      font-size: 1rem;
      color: var(--primary-text-color);
    }
    input[type="text"] {
      box-sizing: border-box;
      width: 100%;
      font: inherit;
      color: var(--primary-text-color);
      background: var(--card-background-color, var(--ha-card-background));
      border: 1px solid var(--divider-color);
      border-radius: 8px;
      padding: 9px 10px;
    }
    input[type="color"] {
      width: 56px;
      height: 36px;
      padding: 2px;
      border: 1px solid var(--divider-color);
      border-radius: 8px;
      background: none;
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

customElements.define("cospend-manage", CospendManage);
