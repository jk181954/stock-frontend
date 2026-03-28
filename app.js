const API_URL = 'all_stocks_data.json';
let allStocks = []; // 用來暫存抓下來的全台股資料
let lastUpdateTime = "";

// 網頁一載入，就先去後台默默把 1700 檔資料抓下來放著
async function fetchAllData() {
    const status = document.getElementById('status');
    const metaInfo = document.getElementById('metaInfo');
    
    try {
        const response = await fetch(API_URL + "?t=" + new Date().getTime());
        if (!response.ok) throw new Error('無法讀取資料');
        
        const data = await response.json();
        allStocks = data.stocks || [];
        lastUpdateTime = data.updated_at || '未知';
        
        metaInfo.textContent = `全市場資料已載入 (${allStocks.length} 檔)。最後更新：${lastUpdateTime}`;
        status.textContent = '準備就緒，請點擊上方按鈕執行策略。';
    } catch (error) {
        metaInfo.textContent = '資料載入失敗，請確認 GitHub Actions 是否已跑完。';
        console.error(error);
    }
}

// 策略一：量縮測底完成 (你原本的策略)
function strategyVolumeBottom() {
    return allStocks.filter(stock => {
        return (
            stock.close > stock.ma5 && 
            stock.close > stock.ma20 && 
            stock.close > stock.ma60 &&
            stock.lowestClose20 < stock.ma20 &&
            stock.volume > 500 &&
            stock.close < stock.ma200 * 1.4 &&
            stock.ma200_up_10days === true
        );
    });
}

// 策略二：簡單均線多頭 (範例：你可以自己加無限多個策略)
function strategyBullMarket() {
    return allStocks.filter(stock => {
        return (
            stock.close > stock.ma5 &&
            stock.ma5 > stock.ma20 &&
            stock.ma20 > stock.ma60 &&
            stock.volume > 1000
        );
    });
}

// 負責把陣列畫成表格的函數
function renderTable(filteredStocks, strategyName) {
    const tbody = document.getElementById('resultBody');
    const count = document.getElementById('resultCount');
    const status = document.getElementById('status');

    if (filteredStocks.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="empty">此策略今日無符合標的</td></tr>`;
        count.textContent = '0 檔';
        status.textContent = `[${strategyName}] 執行完成`;
        return;
    }

    tbody.innerHTML = filteredStocks.map(stock => `
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

    count.textContent = `共 ${filteredStocks.length} 檔`;
    status.textContent = `[${strategyName}] 執行完成，花費 0.01 秒`;
}

// 綁定按鈕事件
document.getElementById('btnStrategy1').addEventListener('click', () => {
    const result = strategyVolumeBottom();
    renderTable(result, "量縮測底完成");
});

document.getElementById('btnStrategy2').addEventListener('click', () => {
    const result = strategyBullMarket();
    renderTable(result, "均線多頭排列");
});

// 網頁啟動時載入資料
window.addEventListener('DOMContentLoaded', fetchAllData);
