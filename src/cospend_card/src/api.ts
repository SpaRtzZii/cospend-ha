import type { BillItem, BillsPage, HassLike, Project } from "./types";

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

/** Prévient à chaque mise à jour des données ; renvoie la fonction de désinscription. */
export function subscribeChanges(hass: HassLike, onChange: () => void): Promise<() => void> {
  return hass.connection.subscribeMessage(() => onChange(), { type: "cospend/subscribe" });
}
