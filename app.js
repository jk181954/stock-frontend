async function loadStocks() {
  const response = await fetch('stocks.json');
  if (!response.ok) {
    throw new Error('無法讀取 stocks.json');
  }
  return await response.json();
}

function matchStrategy(stock) {
  return (
    stock.close > stock.ma5 &&
    stock.close > stock.ma20 &&
    stock.close > stock.ma60 &&
    stock.lowestClose20 < stock.ma20 &&
    stock.volume > 500 &&
    stock.close < stock.ma200 * 1.4 &&
    stock.ma200_up_10days === true
  );
}

function renderResults(results) {
  const tbody = document.getElementById('resultBody');
  const count = document.getElementById('resultCount');

  if (results.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" class="empty">沒有符合條件的股票</td>
      </tr>
    `;
    count.textContent = '0 檔';
    return;
  }

  tbody.innerHTML = results.map(stock => `
    <tr>
      <td>${stock.code}</td>
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

  count.textContent = `共 ${results.length} 檔`;
}

async function runStrategy() {
  const tbody = document.getElementById('resultBody');
  const count = document.getElementById('resultCount');

  try {
    count.textContent = '執行中...';
    tbody.innerHTML = `
      <tr>
        <td colspan="9" class="empty">資料讀取中...</td>
      </tr>
    `;

    const stocks = await loadStocks();
    const results = stocks.filter(matchStrategy);
    renderResults(results);
  } catch (error) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" class="empty">發生錯誤：${error.message}</td>
      </tr>
    `;
    count.textContent = '錯誤';
  }
}

document.getElementById('runBtn').addEventListener('click', runStrategy);
