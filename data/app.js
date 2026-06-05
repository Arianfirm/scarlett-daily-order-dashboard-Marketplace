fetch('./data/orders.json')
  .then(res => res.json())
  .then(data => {
      document.getElementById('orders').innerText = data.orders_today;
      document.getElementById('qty').innerText = data.qty_today;
      document.getElementById('marketplace').innerText = data.top_marketplace;
      document.getElementById('sku').innerText = data.top_sku;
  });
