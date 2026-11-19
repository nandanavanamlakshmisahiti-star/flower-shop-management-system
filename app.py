"""
Flower Shop Management System - project demo
Run:  python app.py      then open  http://localhost:8000
Needs only Python 3.8+ (standard library: http.server + sqlite3).
"""
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

DB = "flowershop.db"
PORT = 8000


# ---------- Database ----------
def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS flowers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'Fresh',
        price REAL NOT NULL CHECK(price >= 0),
        stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0)
    );
    CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        address TEXT
    );
    CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER REFERENCES customers(id),
        total REAL NOT NULL,
        created TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS order_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        flower_id INTEGER NOT NULL REFERENCES flowers(id),
        qty INTEGER NOT NULL,
        price REAL NOT NULL
    );
    """)
    if conn.execute("SELECT COUNT(*) FROM flowers").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO flowers(name,category,price,stock) VALUES(?,?,?,?)",
            [("Red Rose", "Rose", 30, 100), ("Tulip", "Seasonal", 25, 60),
             ("Lily", "Fresh", 40, 45), ("Marigold", "Garland", 10, 200),
             ("Orchid", "Exotic", 120, 20), ("Sunflower", "Fresh", 35, 50)])
        conn.executemany(
            "INSERT INTO customers(name,phone,address) VALUES(?,?,?)",
            [("Walk-in Customer", "", ""), ("Asha Rao", "9876543210", "MG Road")])
    conn.commit()
    conn.close()


# ---------- API logic ----------
def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def create_order(conn, data):
    items = data.get("items", [])
    if not items:
        raise ValueError("Order has no items")
    total = 0
    priced = []
    for it in items:
        qty = int(it["qty"])
        if qty <= 0:
            raise ValueError("Quantity must be positive")
        f = conn.execute("SELECT * FROM flowers WHERE id=?", (it["flower_id"],)).fetchone()
        if not f:
            raise ValueError("Flower not found")
        if f["stock"] < qty:
            raise ValueError(f"Not enough stock for {f['name']} (have {f['stock']})")
        total += qty * f["price"]
        priced.append((f["id"], qty, f["price"]))
    cur = conn.execute("INSERT INTO orders(customer_id,total) VALUES(?,?)",
                       (data.get("customer_id"), total))
    oid = cur.lastrowid
    for fid, qty, price in priced:
        conn.execute("INSERT INTO order_items(order_id,flower_id,qty,price) VALUES(?,?,?,?)",
                     (oid, fid, qty, price))
        conn.execute("UPDATE flowers SET stock=stock-? WHERE id=?", (qty, fid))
    return {"id": oid, "total": total}


def handle(method, path, data):
    conn = db()
    try:
        if path == "/api/flowers":
            if method == "GET":
                return rows(conn.execute("SELECT * FROM flowers ORDER BY name"))
            if method == "POST":
                conn.execute("INSERT INTO flowers(name,category,price,stock) VALUES(?,?,?,?)",
                             (data["name"], data.get("category", "Fresh"),
                              float(data["price"]), int(data["stock"])))
                conn.commit()
                return {"ok": True}
        m = re.fullmatch(r"/api/flowers/(\d+)", path)
        if m:
            fid = int(m.group(1))
            if method == "PUT":
                conn.execute("UPDATE flowers SET name=?,category=?,price=?,stock=? WHERE id=?",
                             (data["name"], data["category"], float(data["price"]),
                              int(data["stock"]), fid))
                conn.commit()
                return {"ok": True}
            if method == "DELETE":
                conn.execute("DELETE FROM flowers WHERE id=?", (fid,))
                conn.commit()
                return {"ok": True}
        if path == "/api/customers":
            if method == "GET":
                return rows(conn.execute("SELECT * FROM customers ORDER BY name"))
            if method == "POST":
                conn.execute("INSERT INTO customers(name,phone,address) VALUES(?,?,?)",
                             (data["name"], data.get("phone", ""), data.get("address", "")))
                conn.commit()
                return {"ok": True}
        if path == "/api/orders":
            if method == "GET":
                return rows(conn.execute("""
                    SELECT o.id, o.created, o.total, c.name AS customer,
                      (SELECT group_concat(f.name || ' x' || i.qty, ', ')
                         FROM order_items i JOIN flowers f ON f.id=i.flower_id
                        WHERE i.order_id=o.id) AS items
                    FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
                    ORDER BY o.id DESC"""))
            if method == "POST":
                res = create_order(conn, data)
                conn.commit()
                return res
        if path == "/api/stats" and method == "GET":
            s = conn.execute("""SELECT
                (SELECT COUNT(*) FROM flowers) AS flowers,
                (SELECT COUNT(*) FROM customers) AS customers,
                (SELECT COUNT(*) FROM orders) AS orders,
                (SELECT IFNULL(SUM(total),0) FROM orders) AS revenue""").fetchone()
            low = rows(conn.execute("SELECT name, stock FROM flowers WHERE stock<=20 ORDER BY stock"))
            return {**dict(s), "low_stock": low}
        raise LookupError("Not found")
    except sqlite3.Error as e:
        conn.rollback()
        raise ValueError(str(e))
    finally:
        conn.close()


# ---------- HTTP server ----------
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _api(self, method):
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}") if n else {}
            self._send(200, json.dumps(handle(method, self.path.split("?")[0], data)))
        except LookupError as e:
            self._send(404, json.dumps({"error": str(e)}))
        except (ValueError, KeyError, TypeError) as e:
            self._send(400, json.dumps({"error": str(e)}))

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        self._send(200, PAGE, "text/html; charset=utf-8")

    def do_POST(self): self._api("POST")
    def do_PUT(self): self._api("PUT")
    def do_DELETE(self): self._api("DELETE")

    def log_message(self, *a):
        pass


# ---------- Front end ----------
PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flower Shop Management</title>
<style>
 body{font-family:system-ui,sans-serif;margin:0;background:#fdf6f8;color:#333}
 header{background:#c2185b;color:#fff;padding:14px 20px;font-size:20px}
 nav{display:flex;gap:6px;padding:10px 20px;background:#f8bbd0;flex-wrap:wrap}
 nav button{border:0;padding:8px 14px;border-radius:6px;cursor:pointer;background:#fff}
 nav button.on{background:#c2185b;color:#fff}
 main{padding:20px;max-width:1000px;margin:auto}
 .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
 .card{background:#fff;padding:16px;border-radius:10px;box-shadow:0 1px 4px #0002}
 .card b{font-size:26px;display:block;color:#c2185b}
 table{width:100%;border-collapse:collapse;background:#fff;margin:12px 0;border-radius:8px;overflow:hidden}
 th,td{padding:8px 10px;border-bottom:1px solid #eee;text-align:left;font-size:14px}
 th{background:#fce4ec}
 input,select{padding:7px;margin:3px;border:1px solid #ccc;border-radius:5px}
 .btn{background:#c2185b;color:#fff;border:0;padding:8px 14px;border-radius:6px;cursor:pointer}
 .del{background:#888;padding:4px 9px}
 .msg{color:#c2185b;min-height:20px}
 .low{color:#d32f2f}
</style></head><body>
<header>🌸 Flower Shop Management System</header>
<nav id="nav"></nav>
<main id="main"></main>
<script>
const tabs=['Dashboard','Inventory','Customers','New Order','Orders'];
let cur='Dashboard', cart=[];
const api=async(m,u,b)=>{const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
  const j=await r.json(); if(!r.ok) throw new Error(j.error); return j;};
const $=s=>document.querySelector(s);
const money=n=>'₹'+Number(n).toFixed(2);
function nav(){$('#nav').innerHTML=tabs.map(t=>`<button class="${t==cur?'on':''}" onclick="go('${t}')">${t}</button>`).join('');}
function go(t){cur=t;nav();({Dashboard:dash,Inventory:inv,Customers:cust,'New Order':newOrder,Orders:orders})[t]();}
function msg(t){const m=$('#msg'); if(m) m.textContent=t;}

async function dash(){
  const s=await api('GET','/api/stats');
  $('#main').innerHTML=`<div class="cards">
   <div class="card"><b>${s.flowers}</b>Flower types</div>
   <div class="card"><b>${s.customers}</b>Customers</div>
   <div class="card"><b>${s.orders}</b>Orders</div>
   <div class="card"><b>${money(s.revenue)}</b>Revenue</div></div>
   <h3>Low stock (≤ 20)</h3>
   ${s.low_stock.length?'<table><tr><th>Flower</th><th>Stock</th></tr>'+s.low_stock.map(l=>`<tr><td>${l.name}</td><td class="low">${l.stock}</td></tr>`).join('')+'</table>':'<p>All stocked up ✅</p>'}`;
}

async function inv(){
  const f=await api('GET','/api/flowers');
  $('#main').innerHTML=`<h3>Add flower</h3>
   <input id="n" placeholder="Name"><input id="c" placeholder="Category"><input id="p" type="number" placeholder="Price"><input id="s" type="number" placeholder="Stock">
   <button class="btn" onclick="addFlower()">Add</button><div class="msg" id="msg"></div>
   <table><tr><th>Name</th><th>Category</th><th>Price</th><th>Stock</th><th></th></tr>
   ${f.map(x=>`<tr><td>${x.name}</td><td>${x.category}</td><td>${money(x.price)}</td>
   <td class="${x.stock<=20?'low':''}">${x.stock}</td>
   <td><button class="btn del" onclick="restock(${x.id},'${x.name}','${x.category}',${x.price},${x.stock})">+Stock</button>
   <button class="btn del" onclick="delFlower(${x.id})">Delete</button></td></tr>`).join('')}</table>`;
}
async function addFlower(){try{await api('POST','/api/flowers',{name:$('#n').value,category:$('#c').value||'Fresh',price:$('#p').value,stock:$('#s').value});inv();}catch(e){msg(e.message)}}
async function restock(id,name,category,price,stock){const q=prompt('Add how many units?');if(!q)return;
  await api('PUT','/api/flowers/'+id,{name,category,price,stock:stock+parseInt(q)});inv();}
async function delFlower(id){if(!confirm('Delete this flower?'))return;try{await api('DELETE','/api/flowers/'+id);inv();}catch(e){alert('Cannot delete: it is used in past orders.')}}

async function cust(){
  const c=await api('GET','/api/customers');
  $('#main').innerHTML=`<h3>Add customer</h3>
   <input id="n" placeholder="Name"><input id="ph" placeholder="Phone"><input id="a" placeholder="Address">
   <button class="btn" onclick="addCust()">Add</button><div class="msg" id="msg"></div>
   <table><tr><th>Name</th><th>Phone</th><th>Address</th></tr>
   ${c.map(x=>`<tr><td>${x.name}</td><td>${x.phone||''}</td><td>${x.address||''}</td></tr>`).join('')}</table>`;
}
async function addCust(){try{await api('POST','/api/customers',{name:$('#n').value,phone:$('#ph').value,address:$('#a').value});cust();}catch(e){msg(e.message)}}

let F=[];
async function newOrder(){
  F=await api('GET','/api/flowers'); const C=await api('GET','/api/customers');
  $('#main').innerHTML=`<h3>Create order</h3>
   Customer: <select id="cu">${C.map(c=>`<option value="${c.id}">${c.name}</option>`).join('')}</select><br>
   <select id="fl">${F.map(f=>`<option value="${f.id}">${f.name} (${money(f.price)}, stock ${f.stock})</option>`).join('')}</select>
   <input id="q" type="number" value="1" min="1" style="width:70px">
   <button class="btn" onclick="addCart()">Add to cart</button>
   <div id="cart"></div><div class="msg" id="msg"></div>`;
  drawCart();
}
function addCart(){const id=+$('#fl').value,q=+$('#q').value,f=F.find(x=>x.id==id);
  if(q<=0)return; cart.push({flower_id:id,name:f.name,price:f.price,qty:q});drawCart();}
function drawCart(){const t=cart.reduce((s,i)=>s+i.qty*i.price,0);
  $('#cart').innerHTML=cart.length?`<table><tr><th>Item</th><th>Qty</th><th>Subtotal</th></tr>
  ${cart.map(i=>`<tr><td>${i.name}</td><td>${i.qty}</td><td>${money(i.qty*i.price)}</td></tr>`).join('')}
  <tr><th colspan=2>Total</th><th>${money(t)}</th></tr></table>
  <button class="btn" onclick="placeOrder()">Place order</button>`:'<p>Cart is empty.</p>';}
async function placeOrder(){try{const r=await api('POST','/api/orders',{customer_id:+$('#cu').value,items:cart});
  cart=[];go('Orders');}catch(e){msg(e.message)}}

async function orders(){
  const o=await api('GET','/api/orders');
  $('#main').innerHTML=`<h3>Order history</h3><table><tr><th>#</th><th>Date</th><th>Customer</th><th>Items</th><th>Total</th></tr>
  ${o.map(x=>`<tr><td>${x.id}</td><td>${x.created}</td><td>${x.customer||''}</td><td>${x.items}</td><td>${money(x.total)}</td></tr>`).join('')}</table>`;
}
go('Dashboard');
</script></body></html>"""


if __name__ == "__main__":
    init_db()
    print(f"Flower Shop running at http://localhost:{PORT}  (Ctrl+C to stop)")
    HTTPServer(("", PORT), Handler).serve_forever()
