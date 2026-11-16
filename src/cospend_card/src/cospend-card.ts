import { LitElement, css, html } from "lit";

// Carte Cospend : squelette du jalon M0. Les fonctionnalités arrivent à partir du jalon M5.

interface CospendCardConfig {
  type: string;
  title?: string;
}

interface HomeAssistantLike {
  language?: string;
}

class CospendCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  declare hass?: HomeAssistantLike;
  declare _config?: CospendCardConfig;

  static styles = css`
    ha-card {
      padding: 16px;
    }
    p {
      margin: 8px 0 0;
      color: var(--secondary-text-color);
    }
  `;

  setConfig(config: CospendCardConfig): void {
    this._config = config;
  }

  getCardSize(): number {
    return 2;
  }

  render() {
    const title = this._config?.title ?? "Cospend";
    return html`
      <ha-card header=${title}>
        <p>La carte Cospend est en cours de développement.</p>
      </ha-card>
    `;
  }
}

customElements.define("cospend-card", CospendCard);

declare global {
  interface Window {
    customCards?: Array<{ type: string; name: string; description: string }>;
  }
}

window.customCards = window.customCards ?? [];
window.customCards.push({
  type: "cospend-card",
  name: "Cospend",
  description: "Gérez vos dépenses partagées Nextcloud Cospend.",
});
