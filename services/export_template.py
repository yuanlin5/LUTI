"""
导出题库的 HTML/CSS/JS 模板。

{QUESTION_DATA} 在生成时被 json.dumps 的题目数组替换。
"""
EXPORT_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>导出题库</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
  background: #F0F2F5; color: #333; line-height: 1.6;
  max-width: 960px; margin: 0 auto; padding: 16px;
}
h1 { font-size: 24px; color: #4A90D9; margin-bottom: 4px; }
.subtitle { color: #888; font-size: 13px; margin-bottom: 16px; }

/* ---- filter bar ---- */
.filter-bar {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  background: #FFF; border-radius: 8px; padding: 12px 16px;
  margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.filter-bar input { flex: 1 1 180px; min-width: 140px; padding: 6px 10px;
  border: 1px solid #D9D9D9; border-radius: 4px; font-size: 14px; }
.filter-bar select { padding: 6px 8px; border: 1px solid #D9D9D9;
  border-radius: 4px; font-size: 13px; background: #FFF; }
.filter-bar label { font-size: 13px; color: #666; }

/* ---- stats + pagination ---- */
.top-bar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px;
}
.stats { font-size: 13px; color: #888; }
.pagination { display: flex; gap: 8px; align-items: center; font-size: 14px; }
.pagination button {
  padding: 6px 14px; border: 1px solid #D9D9D9; border-radius: 4px;
  background: #FFF; color: #333; cursor: pointer; font-size: 13px;
}
.pagination button:disabled { color: #CCC; cursor: default; }
.pagination button:hover:not(:disabled) { border-color: #4A90D9; color: #4A90D9; }
.page-num { font-size: 13px; color: #555; min-width: 100px; text-align: center; }

/* ---- cards ---- */
.card {
  background: #FFF; border-radius: 8px; padding: 16px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.card-header {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin-bottom: 10px; font-size: 13px;
}
.card-num { font-weight: bold; color: #4A90D9; font-size: 15px; margin-right: 8px; }
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 12px; background: #E6F0FF; color: #4A90D9;
}
.badge-tag { background: #F0F0F0; color: #666; }
.badge-wrong { background: #FFF0F0; color: #FF4D4F; }

.question-body { margin-bottom: 12px; }
.question-body img { max-width: 100%; height: auto; border-radius: 4px;
  display: block; margin: 8px 0; }
.q-text { white-space: pre-wrap; word-break: break-word; }

/* ---- answer ---- */
details.answer-block { margin-top: 8px; }
details.answer-block > summary {
  cursor: pointer; list-style: none;
  background: #E8E8E8; color: #555; padding: 8px 14px;
  border-radius: 6px; font-size: 14px; text-align: center;
  user-select: none;
}
details.answer-block > summary::-webkit-details-marker { display: none; }
details.answer-block > summary:hover { background: #DCDCDC; }
details.answer-block[open] > summary { border-radius: 6px 6px 0 0; }

.answer-content {
  background: #FAFAFA; padding: 12px 14px; border-radius: 0 0 6px 6px;
  border: 1px solid #E8E8E8; border-top: none;
}
.answer-content img { max-width: 100%; height: auto; border-radius: 4px;
  display: block; margin: 8px 0; }

.notes-text { margin-top: 8px; padding-top: 8px; border-top: 1px dashed #E0E0E0;
  font-size: 13px; color: #888; white-space: pre-wrap; word-break: break-word; }

.img-broken {
  display: block; padding: 20px; text-align: center; color: #CCC;
  border: 1px dashed #E0E0E0; border-radius: 4px; font-size: 13px;
}

/* ---- footer ---- */
.footer-bar { margin-top: 16px; }
.footer { text-align: center; color: #BBB; font-size: 12px;
  margin-top: 24px; padding-top: 16px; border-top: 1px solid #EEE; }
</style>
</head>
<body>

<h1>导出题库</h1>
<div class="subtitle">
  导出时间: <span id="exportTime"></span> &nbsp;|&nbsp;
  共 <span id="totalCount">0</span> 题 &nbsp;|&nbsp;
  当前筛选: <span id="filteredCount">0</span> 题
</div>

<div class="filter-bar">
  <label>搜索:</label>
  <input type="text" id="keyword" placeholder="输入关键词..." oninput="applyFilters()">
  <label>分类:</label>
  <select id="catFilter" onchange="applyFilters()"><option value="">全部分类</option></select>
  <label>标签:</label>
  <select id="tagFilter" onchange="applyFilters()"><option value="">全部标签</option></select>
</div>

<div class="top-bar">
  <div class="stats" id="stats"></div>
  <div class="pagination">
    <button id="prevBtn" onclick="goPage(-1)" disabled>上一页</button>
    <span class="page-num" id="pageInfo">第 1 页</span>
    <button id="nextBtn" onclick="goPage(1)">下一页</button>
  </div>
</div>

<div id="cards"></div>

<div class="footer-bar">
  <div class="pagination" style="justify-content:center">
    <button id="prevBtn2" onclick="goPage(-1)" disabled>上一页</button>
    <span class="page-num" id="pageInfo2">第 1 页</span>
    <button id="nextBtn2" onclick="goPage(1)">下一页</button>
  </div>
</div>

<div class="footer">由 我的题库 生成</div>

<script>
var PAGE_SIZE = 50;
var ALL_DATA = {QUESTION_DATA};
var filtered = [];
var currentPage = 0;

// ---- init ----
(function() {
  if (!Array.isArray(ALL_DATA)) {
    document.getElementById('cards').innerHTML =
      '<div style="text-align:center;padding:60px;color:#FF4D4F;">'
      + '数据加载失败：题目数据格式错误。请重新导出。</div>';
    return;
  }
  document.getElementById('exportTime').textContent =
    new Date().toLocaleString('zh-CN');
  document.getElementById('totalCount').textContent = ALL_DATA.length;
  if (ALL_DATA.length === 0) {
    document.getElementById('cards').innerHTML =
      '<div style="text-align:center;padding:60px;color:#FF4D4F;">'
      + '没有题目数据。导出时可能没有匹配的题目。</div>';
    return;
  }

  // build category/tag dropdowns
  var cats = {}, tags = {};
  ALL_DATA.forEach(function(q) {
    if (q._cat) cats[q._cat] = (cats[q._cat] || 0) + 1;
    (q._tags || []).forEach(function(t) { tags[t] = (tags[t] || 0) + 1; });
  });
  function fillSelect(id, map) {
    var sel = document.getElementById(id);
    Object.keys(map).sort().forEach(function(k) {
      var o = document.createElement('option');
      o.value = k; o.textContent = k + ' (' + map[k] + ')';
      sel.appendChild(o);
    });
  }
  fillSelect('catFilter', cats);
  fillSelect('tagFilter', tags);
  applyFilters();
})();

// ---- filtering ----
function applyFilters() {
  var kw = document.getElementById('keyword').value.trim().toLowerCase();
  var cat = document.getElementById('catFilter').value;
  var tag = document.getElementById('tagFilter').value;
  filtered = ALL_DATA.filter(function(q) {
    if (cat && q._cat !== cat) return false;
    if (tag && (q._tags || []).indexOf(tag) === -1) return false;
    if (kw) {
      var hay = ((q.question_text || '') + ' ' + (q.answer_text || '') +
                 ' ' + (q.notes || '')).toLowerCase();
      if (hay.indexOf(kw) === -1) return false;
    }
    return true;
  });
  document.getElementById('filteredCount').textContent = filtered.length;
  currentPage = 0;
  renderPage();
}

// ---- pagination ----
function goPage(delta) {
  var totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  currentPage = Math.max(0, Math.min(totalPages - 1, currentPage + delta));
  renderPage();
  window.scrollTo(0, 0);
}

function updatePagination() {
  var totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  var info = '第 ' + (currentPage + 1) + ' / ' + totalPages + ' 页';
  document.getElementById('pageInfo').textContent = info;
  document.getElementById('pageInfo2').textContent = info;
  var prevDisabled = currentPage <= 0;
  var nextDisabled = currentPage >= totalPages - 1;
  document.getElementById('prevBtn').disabled = prevDisabled;
  document.getElementById('prevBtn2').disabled = prevDisabled;
  document.getElementById('nextBtn').disabled = nextDisabled;
  document.getElementById('nextBtn2').disabled = nextDisabled;
}

// ---- rendering ----
function renderPage() {
  var start = currentPage * PAGE_SIZE;
  var page = filtered.slice(start, start + PAGE_SIZE);
  var html = '';
  var baseIdx = start;
  page.forEach(function(q, i) {
    var num = baseIdx + i + 1;
    html += '<div class="card">';
    // header
    html += '<div class="card-header">';
    html += '<span class="card-num">#' + num + '</span>';
    if (q._cat) html += '<span class="badge">' + esc(q._cat) + '</span>';
    (q._tags || []).forEach(function(t) {
      html += '<span class="badge badge-tag">' + esc(t) + '</span>';
    });
    if (q.wrong_count > 0) {
      html += '<span class="badge badge-wrong">做错 ' + q.wrong_count + ' 次</span>';
    }
    html += '</div>';

    // question body
    html += '<div class="question-body">';
    var qImgs = (q._images || []).filter(function(im) { return im.t === 'question'; });
    qImgs.forEach(function(im) {
      html += '<img src="' + im.src + '" alt="" loading="lazy" ' +
              'onerror="this.outerHTML=\'<span class=img-broken>图片加载失败</span>\'">';
    });
    if (q.question_text) {
      html += '<div class="q-text">' + esc(q.question_text) + '</div>';
    }
    if (!q.question_text && qImgs.length === 0) {
      html += '<div class="q-text" style="color:#BBB">(无题目内容)</div>';
    }
    html += '</div>';

    // answer
    html += '<details class="answer-block">';
    html += '<summary>点击查看答案</summary>';
    html += '<div class="answer-content">';
    var aImgs = (q._images || []).filter(function(im) { return im.t === 'answer'; });
    aImgs.forEach(function(im) {
      html += '<img src="' + im.src + '" alt="" loading="lazy" ' +
              'onerror="this.outerHTML=\'<span class=img-broken>图片加载失败</span>\'">';
    });
    if (q.answer_text) {
      html += '<div class="q-text">' + esc(q.answer_text) + '</div>';
    }
    if (!q.answer_text && aImgs.length === 0) {
      html += '<div class="q-text" style="color:#BBB">(无答案内容)</div>';
    }
    html += '</div></details>';

    // notes
    if (q.notes) {
      html += '<div class="notes-text">备注: ' + esc(q.notes) + '</div>';
    }
    html += '</div>';
  });

  if (filtered.length === 0) {
    html = '<div style="text-align:center;padding:60px;color:#BBB;">没有匹配的题目</div>';
  }

  document.getElementById('cards').innerHTML = html;
  document.getElementById('stats').textContent =
    '共 ' + filtered.length + ' 题 (本页 ' + page.length + ' 题)';
  updatePagination();
}

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
          .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
</script>
</body>
</html>'''
