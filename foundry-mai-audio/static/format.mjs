export const models = ["MAI-Voice-2.1", "MAI-Voice-2.1-Flash"];
export function estimatedCost(text, model) {
  return Array.from(text).length * (model === models[0] ? 22 : 15) / 1e6;
}
export function updateTranscript(items, event) {
  const id = event.item_id;
  if (!id) return;
  const item = items.get(id) || { stable: "", partial: "", final: false };
  if (item.final) return;
  if (event.type.endsWith(".delta")) {
    item.stable += event.delta || "";
    item.partial = "";
  } else if (event.type.endsWith(".intermediate")) {
    item.partial = event.intermediate || "";
  } else if (event.type.endsWith(".completed")) {
    item.stable = event.transcript || "";
    item.partial = "";
    item.final = true;
  }
  items.set(id, item);
}
