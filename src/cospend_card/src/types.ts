// Formats des réponses de l'API websocket de l'intégration (voir websocket.py).

export interface Member {
  id: number;
  name: string;
  activated: boolean;
  weight: number;
  color: string | null;
  balance: number;
}

export interface Category {
  id: number;
  name: string;
  icon: string;
  color: string;
}

export interface PaymentMode {
  id: number;
  name: string;
  icon: string;
  color: string;
}

export interface Currency {
  id: number;
  name: string;
  exchange_rate: number;
}

export interface Project {
  entry_id: string;
  id: string;
  name: string;
  currency: string | null;
  archived: boolean;
  can_write: boolean;
  access_level: number;
  total_spent: number;
  nb_bills: number;
  pending: number;
  available: boolean;
  members: Member[];
  categories: Category[];
  payment_modes: PaymentMode[];
  currencies: Currency[];
}

export interface ForeignAmount {
  currency: string;
  amount: number;
  rate: number;
}

export interface Share {
  member_id: number;
  name: string;
  amount: number;
}

export interface BillItem {
  ids: number[];
  id: number;
  is_group: boolean;
  what: string;
  amount: number;
  date: string;
  timestamp: number;
  payer_id: number;
  ower_ids: number[];
  category_id: number;
  payment_mode_id: number;
  comment: string;
  repeat: string;
  foreign: ForeignAmount | null;
  pending: boolean;
  shares?: Share[];
  repeat_freq?: number;
  repeat_until?: string | null;
  repeat_all_active?: boolean;
  /** Poids inégaux des participants : une modification les remet à égalité. */
  uneven_weights?: boolean;
}

export interface BillsPage {
  total: number;
  offset: number;
  has_more: boolean;
  items: BillItem[];
}

export interface CospendCardConfig {
  type: string;
  title?: string;
  /** Identifiant du projet à afficher ; sans valeur, un sélecteur est proposé. */
  project?: string;
  entry_id?: string;
  show_balances?: boolean;
  show_bills?: boolean;
  show_search?: boolean;
  page_size?: number;
  /** Autorise l'ajout et la suppression de dépenses depuis la carte (activé par défaut). */
  allow_write?: boolean;
}

/** Réponse des services d'écriture (voir services.py). */
export interface WriteResult {
  project?: string;
  bill_ids?: number[];
  /** ``true`` quand Nextcloud est injoignable : l'opération est en file d'attente. */
  queued?: boolean;
  operation_id?: string;
  /** Identifiant de l'élément créé (service de gestion du projet). */
  id?: number;
}

/** Ce dont la carte a besoin de l'objet ``hass`` de Home Assistant. */
export interface HassLike {
  language?: string;
  user?: { name?: string };
  locale?: { language?: string };
  callWS<T>(message: Record<string, unknown>): Promise<T>;
  connection: {
    subscribeMessage<T>(
      callback: (message: T) => void,
      subscribeMessage: Record<string, unknown>,
    ): Promise<() => void>;
  };
}
