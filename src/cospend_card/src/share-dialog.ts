import { LitElement, css, html, nothing, svg } from "lit";
import type { TemplateResult } from "lit";

import { translate } from "./i18n";
import { qrMatrix, safeShareUrl } from "./qr";
import type { HassLike } from "./types";

/**
 * Fenêtre de partage : QR code et lien public du projet.
 *
 * Ajoutée à ``document.body`` par la carte. Le QR code reste noir sur blanc quel que soit le thème,
 * pour que les lecteurs l'identifient. Émet ``closed`` à la fermeture.
 */
class CospendShareDialog extends LitElement {
  static properties = {
    hass: { attribute: false },
    url: { attribute: false },
    name: { attribute: false },
    _copied: { state: true },
  };

  declare hass?: HassLike;
  declare url: string;
  declare name: string;
  declare _copied: boolean;

  private _opener: Element | null = null;
  private _timer?: ReturnType<typeof setTimeout>;

  constructor() {
    super();
    this.url = "";
    this.name = "";
    this._copied = false;
  }

  connectedCallback(): void {
    super.connectedCallback();
    this._opener = document.activeElement;
    window.addEventListener("keydown", this._onKey);
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

  private _t(key: string): string {
    return translate(this.hass?.locale?.language ?? this.hass?.language, key);
  }

  private _onKey = (event: KeyboardEvent): void => {
    if (event.key === "Escape") this._close();
  };

  private _close(): void {
    this.dispatchEvent(new CustomEvent("closed"));
  }

  private async _copy(): Promise<void> {
    let ok = false;
    try {
      await navigator.clipboard.writeText(this.url);
      ok = true;
    } catch {
      // Contexte non sécurisé ou refus : on retombe sur la sélection du champ.
      const input = this.renderRoot.querySelector("input.link") as HTMLInputElement | null;
      if (input) {
        input.focus();
        input.select();
        try {
          ok = document.execCommand("copy");
        } catch {
          ok = false;
        }
      }
    }
    if (ok) {
      this._copied = true;
      clearTimeout(this._timer);
      this._timer = setTimeout(() => (this._copied = false), 2500);
    }
  }

  private _qr(url: string): TemplateResult {
    const { size, path } = qrMatrix(url);
    return html`<svg
      class="qr"
      viewBox="0 0 ${size} ${size}"
      role="img"
      aria-label=${this._t("share_qr_label")}
      shape-rendering="crispEdges"
    >
      ${svg`<rect width="${size}" height="${size}" fill="#ffffff"></rect><path d="${path}" fill="#000000"></path>`}
    </svg>`;
  }

  protected render(): TemplateResult {
    const url = safeShareUrl(this.url);
    return html`
      <div
        class="backdrop"
        @click=${(e: Event) => e.target === e.currentTarget && this._close()}
      >
        <div
          class="panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="share-title"
          tabindex="-1"
        >
          <div class="head">
            <h2 id="share-title">${this._t("share_title")}</h2>
            <button class="close" aria-label=${this._t("actions_close")} @click=${() => this._close()}>
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
          ${url
            ? html`
                ${this.name ? html`<p class="name">${this.name}</p>` : nothing}
                <div class="qr-wrap">${this._qr(url)}</div>
                <p class="hint">${this._t("share_hint")}</p>
                <div class="link-row">
                  <input class="link" type="text" readonly .value=${url} aria-label=${this._t("share_link")} />
                  <button class="copy" @click=${() => void this._copy()}>
                    <ha-icon icon=${this._copied ? "mdi:check" : "mdi:content-copy"}></ha-icon>
                    <span role="status">${this._copied ? this._t("share_copied") : this._t("share_copy")}</span>
                  </button>
                </div>
                <a class="open" href=${url} target="_blank" rel="noopener noreferrer">
                  <ha-icon icon="mdi:open-in-new"></ha-icon> ${this._t("share_open")}
                </a>
              `
            : html`<p class="error" role="alert">${this._t("share_invalid")}</p>`}
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
      padding: 5vh 12px 12px;
      box-sizing: border-box;
      overflow-y: auto;
      background: rgba(0, 0, 0, 0.5);
    }
    .panel {
      width: 100%;
      max-width: 420px;
      box-sizing: border-box;
      padding: 8px 16px 20px;
      border-radius: var(--ha-card-border-radius, 12px);
      color: var(--primary-text-color);
      background: var(--card-background-color, #fff);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
      outline: none;
    }
    .head {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    h2 {
      flex: 1;
      margin: 12px 0 8px;
      font-size: 1.25rem;
      font-weight: 500;
    }
    .close {
      display: inline-flex;
      padding: 6px;
      color: var(--secondary-text-color);
      background: none;
      border: none;
      border-radius: 50%;
      cursor: pointer;
    }
    .name {
      margin: 0 0 8px;
      color: var(--secondary-text-color);
    }
    .qr-wrap {
      display: flex;
      justify-content: center;
      padding: 8px 0;
    }
    .qr {
      width: min(300px, 100%);
      height: auto;
      border-radius: 8px;
      background: #ffffff;
    }
    .hint {
      margin: 8px 0 12px;
      color: var(--secondary-text-color);
      text-align: center;
    }
    .link-row {
      display: flex;
      gap: 8px;
    }
    .link {
      flex: 1;
      min-width: 0;
      box-sizing: border-box;
      padding: 8px 10px;
      font: inherit;
      color: var(--primary-text-color);
      background: var(--card-background-color, var(--ha-card-background));
      border: 1px solid var(--divider-color);
      border-radius: 8px;
    }
    .copy,
    .open {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      font: inherit;
      color: var(--primary-color);
      background: none;
      border: 1px solid var(--primary-color);
      border-radius: 18px;
      cursor: pointer;
      text-decoration: none;
    }
    .open {
      margin-top: 12px;
      border: none;
      padding-left: 0;
    }
    .copy ha-icon,
    .open ha-icon {
      --mdc-icon-size: 18px;
    }
    .close:focus-visible,
    .copy:focus-visible,
    .open:focus-visible,
    .link:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 2px;
    }
    .error {
      color: var(--error-color);
    }
  `;
}

customElements.define("cospend-share-dialog", CospendShareDialog);
