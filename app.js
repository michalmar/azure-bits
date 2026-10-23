const searchInput = document.getElementById("demoSearch");
const filterButtons = Array.from(document.querySelectorAll("[data-filter]"));
const entries = Array.from(document.querySelectorAll(".demo-entry"));
const statusNode = document.getElementById("catalogStatus");
const emptyState = document.getElementById("catalogEmpty");
const resetButton = document.getElementById("resetCatalogFilters");

let activeFilter = "all";

function normalize(value) {
  return (value || "").toLowerCase().trim();
}

function updateCatalog() {
  const query = normalize(searchInput ? searchInput.value : "");
  let visibleCount = 0;

  for (const entry of entries) {
    const categories = (entry.dataset.category || "").split(/\s+/).filter(Boolean);
    const searchableText = normalize(entry.textContent + " " + (entry.dataset.keywords || ""));
    const matchesCategory = activeFilter === "all" || categories.includes(activeFilter);
    const matchesQuery = !query || searchableText.includes(query);
    const isVisible = matchesCategory && matchesQuery;

    entry.hidden = !isVisible;
    if (isVisible) {
      visibleCount += 1;
    }
  }

  if (emptyState) {
    emptyState.hidden = visibleCount > 0;
  }

  if (statusNode) {
    const total = entries.length;
    if (visibleCount === total && activeFilter === "all" && !query) {
      statusNode.textContent = `Showing all ${total} demos.`;
    } else {
      statusNode.textContent = `Showing ${visibleCount} of ${total} demos.`;
    }
  }
}

for (const button of filterButtons) {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter || "all";
    for (const candidate of filterButtons) {
      const selected = candidate === button;
      candidate.classList.toggle("is-active", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    }
    updateCatalog();
  });
}

if (searchInput) {
  searchInput.addEventListener("input", updateCatalog);
}

if (resetButton) {
  resetButton.addEventListener("click", () => {
    activeFilter = "all";
    if (searchInput) {
      searchInput.value = "";
    }
    for (const candidate of filterButtons) {
      const selected = candidate.dataset.filter === "all";
      candidate.classList.toggle("is-active", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    }
    updateCatalog();
    if (searchInput) {
      searchInput.focus();
    }
  });
}

updateCatalog();
