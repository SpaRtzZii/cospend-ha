import type {
  BillItem,
  BillsPage,
  HassLike,
  Project,
  SettlementPlan,
  Statistics,
  StatsFilters,
  WriteResult,
} from "./types";

export async function fetchProjects(hass: HassLike): Promise<Project[]> {
  const result = await hass.callWS<{ projects: Project[] }>({ type: "cospend/projects" });
  return result.projects;
}

export function fetchBills(
  hass: HassLike,
  project: Pick<Project, "id" | "entry_id">,
  options: { offset?: number; limit?: number; search?: string } = {},
): Promise<BillsPage> {
  return hass.callWS<BillsPage>({
    type: "cospend/bills",
    project_id: project.id,
    entry_id: project.entry_id,
    offset: options.offset ?? 0,
    limit: options.limit ?? 20,
    search: options.search ?? "",
  });
}

export function fetchBill(
  hass: HassLike,
  project: Pick<Project, "id" | "entry_id">,
  billId: number,
): Promise<BillItem> {
  return hass.callWS<BillItem>({
    type: "cospend/bill",
    project_id: project.id,
    entry_id: project.entry_id,
    bill_id: billId,
  });
}

export function fetchSettlement(
  hass: HassLike,
  project: Pick<Project, "id" | "entry_id">,
): Promise<SettlementPlan> {
  return hass.callWS<SettlementPlan>({
    type: "cospend/settlement",
    project_id: project.id,
    entry_id: project.entry_id,
  });
}

export function fetchStatistics(
  hass: HassLike,
  project: Pick<Project, "id" | "entry_id">,
  filters: StatsFilters,
): Promise<Statistics> {
  return hass.callWS<Statistics>({
    type: "cospend/statistics",
    project_id: project.id,
    entry_id: project.entry_id,
    ...filters,
  });
}

/** Prévient à chaque mise à jour des données ; renvoie la fonction de désinscription. */
export function subscribeChanges(hass: HassLike, onChange: () => void): Promise<() => void> {
  return hass.connection.subscribeMessage(() => onChange(), { type: "cospend/subscribe" });
}

async function callService(
  hass: HassLike,
  service: string,
  data: Record<string, unknown>,
): Promise<WriteResult> {
  const result = await hass.callWS<{ response?: WriteResult }>({
    type: "call_service",
    domain: "cospend",
    service,
    service_data: data,
    return_response: true,
  });
  return result.response ?? {};
}

/** Gestion du projet (membres, catégories, modes de paiement, devises) : service ``cospend.*``. */
export function manageProject(
  hass: HassLike,
  service: string,
  data: Record<string, unknown>,
): Promise<WriteResult> {
  return callService(hass, service, data);
}

/** Crée une dépense : ``data`` est déjà au format du service ``cospend.add_bill``. */
export function addBill(hass: HassLike, data: Record<string, unknown>): Promise<WriteResult> {
  return callService(hass, "add_bill", data);
}

/** Modifie une dépense : seuls les champs de ``changes`` (format ``cospend.update_bill``) partent. */
export function updateBill(
  hass: HassLike,
  project: string,
  billId: number,
  changes: Record<string, unknown>,
): Promise<WriteResult> {
  return callService(hass, "update_bill", { project, bill_id: billId, ...changes });
}

/** Supprime une dépense (et tout son groupe pour une répartition personnalisée). */
export function deleteBill(hass: HassLike, project: string, billId: number): Promise<WriteResult> {
  return callService(hass, "delete_bill", { project, bill_id: billId, whole_group: true });
}

/** Message lisible d'une erreur renvoyée par Home Assistant. */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}
