// static/script.js
document.addEventListener("DOMContentLoaded", () => {
  const cols = SERVER.columns;
  const usageColors = SERVER.usage_colors || {};

  const xSelect = document.getElementById("x_col");
  const ySelect = document.getElementById("y_col");
  const updateBtn = document.getElementById("update");
  const degreeSel = document.getElementById("degree");
  const graphTypeSel = document.getElementById("graph_type");
  const searchBox = document.getElementById("search");
  const capMin = document.getElementById("cap_min");
  const capMax = document.getElementById("cap_max");
  const logX = document.getElementById("log_x");
  const logY = document.getElementById("log_y");
  const gridChk = document.getElementById("grid");
  const equationDiv = document.getElementById("equation");

  // セレクトに列をセット
  cols.forEach(c => {
    const o1 = document.createElement("option"); o1.value = c; o1.textContent = c;
    const o2 = document.createElement("option"); o2.value = c; o2.textContent = c;
    xSelect.appendChild(o1);
    ySelect.appendChild(o2);
  });
  // デフォルト
  xSelect.value = "延床面積 [㎡]" in cols ? "延床面積 [㎡]" : cols[0];
  ySelect.value = "合計設備容量 [kVA]" in cols ? "合計設備容量 [kVA]" : cols[Math.min(1, cols.length-1)];

  // フィルタ取得ヘルパー
  function gatherFilters() {
    const filters = {};
    document.querySelectorAll(".filter").forEach(el => {
      const key = el.dataset.key;
      if (!filters[key]) filters[key] = [];
      if (el.checked) filters[key].push(el.value);
    });
    return filters;
  }

  async function fetchAndPlot() {
    const payload = {
      x_col: xSelect.value,
      y_col: ySelect.value,
      degree: degreeSel.value,
      graph_type: graphTypeSel.value,
      filters: gatherFilters(),
      capacity_min: capMin.value,
      capacity_max: capMax.value,
      log_x: logX.checked,
      log_y: logY.checked,
      search: searchBox.value
    };

    const resp = await fetch("/api/get_data", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (resp.status !== 200) {
      alert("データ取得エラー: " + (data.error || "不明"));
      return;
    }

    const traces = data.traces || [];
    // highlight はオプション
    if (data.highlight && data.highlight.length) {
      data.highlight.forEach(h => {
        // ensure distinct style
        traces.push(Object.assign({}, h));
      });
    }
    if (data.fit) {
      traces.push(data.fit);
    }

    // レイアウト
    const layout = {
      paper_bgcolor: "#2E3440",
      plot_bgcolor: "#0B1420",
      margin: {t:40, r:20, l:60, b:60},
      xaxis: Object.assign({gridcolor:"#444444", zerolinecolor:"#444444"}, data.xaxis),
      yaxis: Object.assign({gridcolor:"#444444", zerolinecolor:"#444444"}, data.yaxis),
      legend: {bgcolor: "#2E3440", font: {color:"#ECEFF4"}},
      hovermode: "closest",
    };

    if (!gridChk.checked) {
      layout.xaxis.showgrid = false;
      layout.yaxis.showgrid = false;
    }

    // ツールチップのフォーマット（customdata を利用）
    traces.forEach(t => {
      if (t.type === "scatter" && t.customdata) {
        t.hovertemplate = "%{customdata[0]}<br>発行目的:%{customdata[1]}<br>設計会社:%{customdata[2]}<br>" +
                          `${xSelect.value}: %{x}<br>${ySelect.value}: %{y}<extra></extra>`;
      } else if (t.type === "bar") {
        t.hovertemplate = `${xSelect.value}: %{x}<br>件数: %{y}<extra></extra>`;
      }
    });

    Plotly.react("chart", traces, layout, {responsive:true});
    equationDiv.textContent = data.equation || "";
  }

  // 初回描画
  fetchAndPlot();

  // イベント
  updateBtn.addEventListener("click", fetchAndPlot);
  graphTypeSel.addEventListener("change", () => {
    // ヒストグラムのときは Y軸選択を無効に（フロント上の UX）
    if (graphTypeSel.value === "ヒストグラム") {
      ySelect.disabled = true;
    } else {
      ySelect.disabled = false;
    }
    fetchAndPlot();
  });
  // 変更時に自動更新
  [
    degreeSel, xSelect, ySelect, capMin, capMax, logX, logY, gridChk, searchBox
  ].forEach(el => el.addEventListener("change", fetchAndPlot));
  // フィルタチェックボックスが変わったら更新
  document.querySelectorAll(".filter").forEach(cb => cb.addEventListener("change", fetchAndPlot));

  // グラフ上でクリックしたら詳細を出す（例: 建物行の詳細）
  document.getElementById("chart").on('plotly_click', function(data){
    const pts = data.points && data.points[0];
    if (!pts) return;
    // customdata があるなら表示
    if (pts.customdata) {
      const cd = pts.customdata;
      const name = cd[0] || "";
      const purpose = cd[1] || "";
      const company = cd[2] || "";
      alert(`${name}\n発行目的: ${purpose}\n設計会社: ${company}\n${xSelect.value}: ${pts.x}\n${ySelect.value}: ${pts.y}`);
    }
  });
});
