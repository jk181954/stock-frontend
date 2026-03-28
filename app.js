// 直接讀取目前 Repo 裡的 json 檔
const API_URL = 'stocks.json';

async function runStrategy() {
  const tbody = document.getElementById('resultBody');
  const count = document.getElementById('resultCount');
  const status = document.getElementById('status');
  const metaInfo = document.getElementById('metaInfo');

  status.textContent = '載入最新結果中...';
  tbody.innerHTML = `<tr><td colspan="9" class="empty">讀取中...</td></tr>`;

  try {
    // 給網址加上時間戳，防止瀏覽器讀到舊的暫存檔
    const response = await fetch(API_URL + "?t=" + new Date().getTime());
    if (!response.ok) throw new Error('讀取 JSON 失敗');

    const data = await response.json();
    const stocks = data.stocks || [];
    
    metaInfo.textContent = `更新時間：${data.updated_at}｜掃描 ${data.checked_count} 檔｜符合 ${data.matched_count} 檔`;

    if (stocks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty">今日無符合條件的股票</td></tr>`;
      count.textContent = '0 檔';
      status.textContent = '載入完成';
      return;
    }

    // 這裡加上了玩股網的超連結
    tbody.innerHTML = stocks.map(stock => `
      <tr>
        <td>
          <a href="https://www.wantgoo.com/stock/${stock.code}/technical-chart" target="_blank" style="color: #0f766e; text-decoration: none; font-weight: bold;">
            ${stock.code}
          </a>
        </td>
        <td>${stock.name}</td>
        <td>${stock.close}</td>
        <td>${stock.ma5}</td>
        <td>${stock.ma20}</td>
        <td>${stock.ma60}</td>
        <td>${stock.ma200}</td>
        <td>${stock.lowestClose20}</td>
        <td>${stock.volume}</td>
      </tr>
    `).join('');

    count.textContent = `共 ${stocks.length} 檔`;
    status.textContent = '載入完成';
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">讀取失敗</td></tr>`;
    status.textContent = `錯誤：請確認 GitHub Actions 是否已經跑完並產生 stocks.json`;
  }
}

document.getElementById('runBtn').addEventListener('click', runStrategy);
