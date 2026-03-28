const API_URL = 'https://stock-backend-5ljo.onrender.com/stocks';

async function runStrategy() {
  const tbody = document.getElementById('resultBody');
  const status = document.getElementById('status');

  if (!tbody || !status) {
    alert('找不到 resultBody 或 status，請檢查 index.html');
    return;
  }

  status.textContent = '資料讀取中...';
  tbody.innerHTML = `<tr><td colspan="7">讀取中...</td></tr>`;

  try {
    const response = await fetch(API_URL);
    if (!response.ok) throw new Error('伺服器回應錯誤：' + response.status);

    const stocks = await response.json();

    if (!Array.isArray(stocks)) {
      throw new Error('API 回傳格式不是陣列');
    }

    if (stocks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7">沒有符合條件的股票</td></tr>`;
      status.textContent = '讀取完成';
      return;
    }

    tbody.innerHTML = stocks.map(stock => `
      <tr>
        <td>${stock.code ?? ''}</td>
        <td>${stock.name ?? ''}</td>
        <td>${stock.close ?? ''}</td>
        <td>${stock.ma5 ?? ''}</td>
        <td>${stock.ma20 ?? ''}</td>
        <td>${stock.ma60 ?? ''}</td>
        <td>${stock.volume ?? ''}</td>
      </tr>
    `).join('');

    status.textContent = `讀取完成，共 ${stocks.length} 檔`;
  } catch (error) {
    console.error(error);
    tbody.innerHTML = `<tr><td colspan="7">讀取失敗</td></tr>`;
    status.textContent = `錯誤：${error.message}`;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  const runBtn = document.getElementById('runBtn');

  if (!runBtn) {
    console.error('找不到 runBtn');
    return;
  }

  runBtn.addEventListener('click', runStrategy);
});
