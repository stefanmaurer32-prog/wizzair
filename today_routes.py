
/* AUTOMATIC 72-HOUR FLIGHT OVERVIEW */

let todayRoutes = [];
let todayLoading = false;
let todayRefreshId = null;

function todaySelect(id, values, label) {
  const element = $(id);
  const previous = element.value;

  element.replaceChildren(
    new Option(label, "")
  );

  const unique = [...new Set(values)]
    .filter(Boolean)
    .sort((a, b) =>
      String(a).localeCompare(String(b), "en")
    );

  for (const value of unique) {
    const text = id === "todayDate"
      ? dateText(value)
      : cityText(value);

    element.add(
      new Option(text, value)
    );
  }

  if (unique.includes(previous)) {
    element.value = previous;
  }
}

function renderToday() {
  const selectedDate = $("todayDate").value;
  const selectedFrom = $("todayFrom").value;
  const selectedTo = $("todayTo").value;

  const filtered = todayRoutes.filter(route => {
    return (
      (!selectedDate ||
        route.date === selectedDate) &&
      (!selectedFrom ||
        route.from === selectedFrom) &&
      (!selectedTo ||
        route.to === selectedTo)
    );
  });

  $("todayCount").textContent =
    filtered.length +
    " direct routes displayed";

  if (!filtered.length) {
    $("todayResults").innerHTML = `
      <p class="hint">
        No matching routes found.
      </p>
    `;
    return;
  }

  // Display ALL results, without pagination.
  $("todayResults").innerHTML =
    filtered.map((route, index) => `
      <div class="today-row">

        <strong>
          ✈️ ${esc(cityText(route.from))}
          →
          ${esc(cityText(route.to))}
        </strong>

        <div class="hint">
          📅 ${esc(dateText(route.date))}
        </div>

        <div class="hint">
          Route ${index + 1}
          · Direct flight
          · Flight time not confirmed
          · AYCF seat not confirmed
        </div>

      </div>
    `).join("");
}

$("todayDate").onchange = renderToday;
$("todayFrom").onchange = renderToday;
$("todayTo").onchange = renderToday;

async function loadToday() {
  if (todayLoading) return;

  todayLoading = true;

  try {
    const data = await getJSON(
      "/api/radar/today"
    );

    todayRoutes = Array.isArray(data.routes)
      ? data.routes
      : [];

    todaySelect(
      "todayDate",
      todayRoutes.map(route => route.date),
      "All dates – Next 72 hours"
    );

    todaySelect(
      "todayFrom",
      todayRoutes.map(route => route.from),
      "All departures"
    );

    todaySelect(
      "todayTo",
      todayRoutes.map(route => route.to),
      "All destinations"
    );

    const progress = data.total
      ? ` (${data.processed}/${data.total} checked)`
      : "";

    if (data.state === "ready") {
      $("todayStatus").textContent =
        `✓ ${todayRoutes.length} direct routes found ` +
        `– Scan complete`;

    } else if (data.state === "error") {
      $("todayStatus").textContent =
        data.error ||
        "Flight overview unavailable.";

    } else {
      $("todayStatus").textContent =
        `Checking next 72 hours ...${progress}` +
        ` – ${todayRoutes.length} routes found`;
    }

    renderToday();

    clearTimeout(todayRefreshId);

    if (data.state === "loading") {
      todayRefreshId = setTimeout(
        loadToday,
        3500
      );
    }

  } catch (error) {
    $("todayStatus").textContent =
      "Flight overview unavailable: " +
      error.message;

  } finally {
    todayLoading = false;
  }
}

loadToday();

setInterval(() => {
  if (!todayLoading) {
    loadToday();
  }
}, 15 * 60 * 1000);
