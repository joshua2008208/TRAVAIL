"""
╔══════════════════════════════════════════════════════════════════╗
║           PIJI Stock Pro — API Flask                             ║
║           Backend adapté pour Railway + Supabase                 ║
║                                                                  ║
║  Variables d'environnement Railway à configurer :               ║
║    DATABASE_URL  → URI PostgreSQL Supabase                       ║
║    SECRET_KEY    → clé secrète aléatoire                         ║
║    ALLOWED_ORIGINS → URL du fichier HTML (ex: https://monsite.com)║
║    PORT          → géré automatiquement par Railway              ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
from datetime import datetime, date
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import psycopg2.pool
import decimal

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'piji-secret-change-me')

# CORS
raw_origins = os.environ.get('ALLOWED_ORIGINS', '*')
origins = [o.strip() for o in raw_origins.split(',')] if raw_origins != '*' else '*'
CORS(app, resources={r"/api/*": {"origins": origins}}, supports_credentials=True)

# DB
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=10,
            dsn=DATABASE_URL,
            cursor_factory=RealDictCursor
        )
    return _pool

class DBCtx:
    def __enter__(self):
        self.conn = get_pool().getconn()
        self.cur = self.conn.cursor()
        return self.cur, self.conn
    def __exit__(self, exc_type, *_):
        if exc_type: self.conn.rollback()
        else:        self.conn.commit()
        get_pool().putconn(self.conn)

def db():
    return DBCtx()

def row2d(row):
    if row is None: return None
    r = {}
    for k, v in dict(row).items():
        if isinstance(v, decimal.Decimal): r[k] = float(v)
        elif isinstance(v, (date, datetime)): r[k] = str(v)
        else: r[k] = v
    return r

def rows2l(rows): return [row2d(r) for r in rows]
def sf(v):
    try: return float(v or 0)
    except: return 0.0
def si(v):
    try: return int(v or 0)
    except: return 0
def today(): return datetime.now().strftime('%d/%m/%Y')

SCHEMA = """
CREATE TABLE IF NOT EXISTS produit (
    id_prod SERIAL PRIMARY KEY, ref_prod VARCHAR(50) UNIQUE,
    nom_prod VARCHAR(200) NOT NULL, cat_prod VARCHAR(100), desc_prod TEXT,
    pa_prod NUMERIC(15,2) DEFAULT 0, pv_prod NUMERIC(15,2) DEFAULT 0,
    taux_tva NUMERIC(5,2) DEFAULT 0, q_prod INTEGER DEFAULT 0, q_min_prod INTEGER DEFAULT 5
);
CREATE TABLE IF NOT EXISTS client (
    id_clt SERIAL PRIMARY KEY, nom_clt VARCHAR(100) NOT NULL,
    prenom_clt VARCHAR(100), em_clt VARCHAR(200), tel_clt VARCHAR(50),
    ad_clt TEXT, tva_intra VARCHAR(50)
);
CREATE TABLE IF NOT EXISTS fournisseur (
    id_four SERIAL PRIMARY KEY, nom_four VARCHAR(200) NOT NULL,
    tel_four VARCHAR(50), ad_four TEXT
);
CREATE TABLE IF NOT EXISTS ventes (
    id_v SERIAL PRIMARY KEY, id_clt INTEGER REFERENCES client(id_clt) ON DELETE SET NULL,
    date_achat_v VARCHAR(20), total_v NUMERIC(15,2) DEFAULT 0,
    moyen_paiement VARCHAR(30) DEFAULT 'espece', ref_transaction VARCHAR(100),
    operateur_mobile VARCHAR(20), credit_paye NUMERIC(15,2) DEFAULT 0,
    credit_reste NUMERIC(15,2) DEFAULT 0
);
CREATE TABLE IF NOT EXISTS details_ventes (
    id_dv SERIAL PRIMARY KEY, id_v INTEGER REFERENCES ventes(id_v) ON DELETE CASCADE,
    id_prod INTEGER REFERENCES produit(id_prod) ON DELETE SET NULL,
    quantite INTEGER DEFAULT 1, pu NUMERIC(15,2) DEFAULT 0,
    pa_prod NUMERIC(15,2) DEFAULT 0, taux_tva NUMERIC(5,2) DEFAULT 0,
    sous_total NUMERIC(15,2) DEFAULT 0, sous_total_ttc NUMERIC(15,2) DEFAULT 0
);
CREATE TABLE IF NOT EXISTS achats (
    id_achat SERIAL PRIMARY KEY, id_four INTEGER REFERENCES fournisseur(id_four) ON DELETE SET NULL,
    date_achat VARCHAR(20), total_tva NUMERIC(15,2) DEFAULT 0, statut VARCHAR(30) DEFAULT 'recu'
);
CREATE TABLE IF NOT EXISTS details_achats (
    id_da SERIAL PRIMARY KEY, id_achat INTEGER REFERENCES achats(id_achat) ON DELETE CASCADE,
    id_prod INTEGER REFERENCES produit(id_prod) ON DELETE SET NULL,
    quantite INTEGER DEFAULT 1, pu_d_a NUMERIC(15,2) DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paiements_credit (
    id_paiement SERIAL PRIMARY KEY, id_v INTEGER REFERENCES ventes(id_v) ON DELETE CASCADE,
    montant NUMERIC(15,2) DEFAULT 0, date_paiement VARCHAR(20), note TEXT
);
CREATE TABLE IF NOT EXISTS factures (
    id_fact SERIAL PRIMARY KEY, id_v INTEGER REFERENCES ventes(id_v) ON DELETE CASCADE,
    num_fact INTEGER, date_fact VARCHAR(20)
);
"""

def init_db():
    with db() as (cur, _):
        cur.execute(SCHEMA)
    print("DB initialisee.")

@app.route('/')
def health(): return jsonify({'status':'ok','app':'PIJI Stock Pro','version':'2.0'})

@app.route('/api/ping')
def ping(): return jsonify({'pong':True})

@app.route('/api/dashboard')
def dashboard():
    mois = datetime.now().strftime('%m/%Y')
    with db() as (cur, _):
        def cnt(t): cur.execute(f"SELECT COUNT(*) AS n FROM {t}"); return cur.fetchone()['n']
        cur.execute("SELECT COALESCE(SUM(total_v),0) AS ca FROM ventes WHERE date_achat_v LIKE %s", (f'%/{mois}',))
        ca_mois = float(cur.fetchone()['ca'])
        cur.execute("SELECT COALESCE(SUM(total_v),0) AS ca FROM ventes")
        ca_total = float(cur.fetchone()['ca'])
        cur.execute("SELECT COUNT(*) AS n FROM produit WHERE q_prod <= q_min_prod")
        alertes = cur.fetchone()['n']
        cur.execute("SELECT COALESCE(SUM(pv_prod*q_prod),0) AS v FROM produit")
        val_stock = float(cur.fetchone()['v'])
        cur.execute("""SELECT v.id_v,v.date_achat_v,v.total_v,
            CONCAT(c.nom_clt,' ',COALESCE(c.prenom_clt,'')) AS client
            FROM ventes v LEFT JOIN client c ON v.id_clt=c.id_clt
            ORDER BY v.id_v DESC LIMIT 5""")
        vr = rows2l(cur.fetchall())
        cur.execute("SELECT id_prod,ref_prod,nom_prod,q_prod,q_min_prod FROM produit WHERE q_prod<=q_min_prod ORDER BY q_prod ASC LIMIT 8")
        ap = rows2l(cur.fetchall())
    return jsonify({'nb_produits':cnt('produit'),'nb_clients':cnt('client'),'nb_fournisseurs':cnt('fournisseur'),
        'nb_ventes':cnt('ventes'),'nb_achats':cnt('achats'),'nb_factures':cnt('factures'),
        'ca_mois':ca_mois,'ca_total':ca_total,'alertes_stock':alertes,'valeur_stock':val_stock,
        'ventes_recentes':vr,'alertes_produits':ap})

@app.route('/api/stats/benefice')
def stats_benefice():
    mois = datetime.now().strftime('%m/%Y')
    with db() as (cur, _):
        cur.execute("""SELECT
            COALESCE(SUM(dv.pu*dv.quantite),0) AS ca_vente,
            COALESCE(SUM(dv.pa_prod*dv.quantite),0) AS ca_achat,
            COALESCE(SUM((dv.pu-dv.pa_prod)*dv.quantite),0) AS benefice_brut
            FROM details_ventes dv JOIN ventes v ON dv.id_v=v.id_v
            WHERE v.date_achat_v LIKE %s""", (f'%/{mois}',))
        r = row2d(cur.fetchone())
    return jsonify({'ca_vente':r['ca_vente'],'ca_achat':r['ca_achat'],'benefice':r['benefice_brut'],'mois':mois})

@app.route('/api/next-id/<string:t>')
def next_id(t):
    m = {'produit':('produit','id_prod'),'client':('client','id_clt'),'fournisseur':('fournisseur','id_four')}
    if t not in m: return jsonify({'error':'Type inconnu'}),400
    tbl,col = m[t]
    with db() as (cur,_):
        cur.execute(f"SELECT COALESCE(MAX({col}),0)+1 AS nxt FROM {tbl}")
        return jsonify({'next_id':cur.fetchone()['nxt']})

# PRODUITS
@app.route('/api/produits', methods=['GET'])
def get_produits():
    with db() as (cur,_):
        cur.execute("SELECT * FROM produit ORDER BY id_prod")
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/produits', methods=['POST'])
def add_produit():
    d = request.json
    if not d.get('nom_prod','').strip(): return jsonify({'error':'Nom obligatoire'}),400
    with db() as (cur,_):
        cur.execute("SELECT COALESCE(MAX(id_prod),0)+1 AS nxt FROM produit")
        nxt = cur.fetchone()['nxt']
        ref = d.get('ref_prod') or f"PRD-{nxt:04d}"
        cur.execute("""INSERT INTO produit (ref_prod,nom_prod,cat_prod,desc_prod,pa_prod,pv_prod,taux_tva,q_prod,q_min_prod)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_prod""",
            (ref,d['nom_prod'],d.get('cat_prod',''),d.get('desc_prod',''),
             sf(d.get('pa_prod')),sf(d.get('pv_prod')),sf(d.get('taux_tva')),
             si(d.get('q_prod')),si(d.get('q_min_prod',5))))
        return jsonify({'id_prod':cur.fetchone()['id_prod']}),201

@app.route('/api/produits/<int:id_>', methods=['PUT'])
def update_produit(id_):
    d = request.json
    with db() as (cur,_):
        cur.execute("""UPDATE produit SET nom_prod=%s,ref_prod=%s,cat_prod=%s,desc_prod=%s,
            pa_prod=%s,pv_prod=%s,taux_tva=%s,q_prod=%s,q_min_prod=%s WHERE id_prod=%s""",
            (d.get('nom_prod'),d.get('ref_prod'),d.get('cat_prod'),d.get('desc_prod'),
             sf(d.get('pa_prod')),sf(d.get('pv_prod')),sf(d.get('taux_tva')),
             si(d.get('q_prod')),si(d.get('q_min_prod',5)),id_))
    return jsonify({'ok':True})

@app.route('/api/produits/<int:id_>', methods=['DELETE'])
def del_produit(id_):
    with db() as (cur,_): cur.execute("DELETE FROM produit WHERE id_prod=%s",(id_,))
    return jsonify({'ok':True})

# STOCK ALERTES
@app.route('/api/stock/alertes')
def stock_alertes():
    with db() as (cur,_):
        cur.execute("SELECT id_prod,ref_prod,nom_prod,cat_prod,q_prod,q_min_prod FROM produit WHERE q_prod<=q_min_prod ORDER BY q_prod")
        return jsonify(rows2l(cur.fetchall()))

# CLIENTS
@app.route('/api/clients', methods=['GET'])
def get_clients():
    with db() as (cur,_):
        cur.execute("SELECT * FROM client ORDER BY id_clt")
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/clients', methods=['POST'])
def add_client():
    d = request.json
    if not d.get('nom_clt','').strip(): return jsonify({'error':'Nom obligatoire'}),400
    with db() as (cur,_):
        cur.execute("INSERT INTO client (nom_clt,prenom_clt,em_clt,tel_clt,ad_clt,tva_intra) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id_clt",
            (d['nom_clt'],d.get('prenom_clt',''),d.get('em_clt',''),d.get('tel_clt',''),d.get('ad_clt',''),d.get('tva_intra','')))
        return jsonify({'id_clt':cur.fetchone()['id_clt']}),201

@app.route('/api/clients/<int:id_>', methods=['PUT'])
def update_client(id_):
    d = request.json
    with db() as (cur,_):
        cur.execute("UPDATE client SET nom_clt=%s,prenom_clt=%s,em_clt=%s,tel_clt=%s,ad_clt=%s,tva_intra=%s WHERE id_clt=%s",
            (d.get('nom_clt'),d.get('prenom_clt'),d.get('em_clt'),d.get('tel_clt'),d.get('ad_clt'),d.get('tva_intra'),id_))
    return jsonify({'ok':True})

@app.route('/api/clients/<int:id_>', methods=['DELETE'])
def del_client(id_):
    with db() as (cur,_): cur.execute("DELETE FROM client WHERE id_clt=%s",(id_,))
    return jsonify({'ok':True})

# FOURNISSEURS
@app.route('/api/fournisseurs', methods=['GET'])
def get_fours():
    with db() as (cur,_):
        cur.execute("SELECT * FROM fournisseur ORDER BY id_four")
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/fournisseurs', methods=['POST'])
def add_four():
    d = request.json
    if not d.get('nom_four','').strip(): return jsonify({'error':'Nom obligatoire'}),400
    with db() as (cur,_):
        cur.execute("INSERT INTO fournisseur (nom_four,tel_four,ad_four) VALUES (%s,%s,%s) RETURNING id_four",
            (d['nom_four'],d.get('tel_four',''),d.get('ad_four','')))
        return jsonify({'id_four':cur.fetchone()['id_four']}),201

@app.route('/api/fournisseurs/<int:id_>', methods=['PUT'])
def update_four(id_):
    d = request.json
    with db() as (cur,_):
        cur.execute("UPDATE fournisseur SET nom_four=%s,tel_four=%s,ad_four=%s WHERE id_four=%s",
            (d.get('nom_four'),d.get('tel_four'),d.get('ad_four'),id_))
    return jsonify({'ok':True})

@app.route('/api/fournisseurs/<int:id_>', methods=['DELETE'])
def del_four(id_):
    with db() as (cur,_): cur.execute("DELETE FROM fournisseur WHERE id_four=%s",(id_,))
    return jsonify({'ok':True})

# VENTES
@app.route('/api/ventes', methods=['GET'])
def get_ventes():
    with db() as (cur,_):
        cur.execute("""SELECT v.*,CONCAT(c.nom_clt,' ',COALESCE(c.prenom_clt,'')) AS client_nom
            FROM ventes v LEFT JOIN client c ON v.id_clt=c.id_clt ORDER BY v.id_v DESC""")
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/ventes', methods=['POST'])
def add_vente():
    d = request.json
    lignes = d.get('lignes',[])
    if not lignes: return jsonify({'error':'Aucun article'}),400
    with db() as (cur,_):
        ids = [l['id_prod'] for l in lignes]
        cur.execute("SELECT id_prod,pv_prod,pa_prod,taux_tva FROM produit WHERE id_prod = ANY(%s)",(ids,))
        prods = {r['id_prod']:row2d(r) for r in cur.fetchall()}
        total_ttc = 0.0; lc = []
        for l in lignes:
            p = prods.get(l['id_prod'])
            if not p: continue
            qty=si(l.get('quantite',1)); pu=sf(l.get('pu',p['pv_prod']))
            pa=sf(p['pa_prod']); tva=sf(l.get('taux_tva',p['taux_tva']))
            st=pu*qty; sttc=st*(1+tva/100); total_ttc+=sttc
            lc.append({'id':l['id_prod'],'qty':qty,'pu':pu,'pa':pa,'tva':tva,'st':st,'sttc':sttc})
        moyen=d.get('moyen_paiement','espece')
        cr_paye=sf(d.get('credit_paye',0)); cr_rest=sf(d.get('credit_reste',0))
        if moyen!='credit': cr_paye=total_ttc; cr_rest=0.0
        cur.execute("""INSERT INTO ventes (id_clt,date_achat_v,total_v,moyen_paiement,ref_transaction,operateur_mobile,credit_paye,credit_reste)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id_v""",
            (d.get('id_clt'),today(),round(total_ttc,2),moyen,d.get('ref_transaction',''),d.get('operateur_mobile',''),cr_paye,cr_rest))
        id_v = cur.fetchone()['id_v']
        for l in lc:
            cur.execute("""INSERT INTO details_ventes (id_v,id_prod,quantite,pu,pa_prod,taux_tva,sous_total,sous_total_ttc)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",(id_v,l['id'],l['qty'],l['pu'],l['pa'],l['tva'],round(l['st'],2),round(l['sttc'],2)))
            cur.execute("UPDATE produit SET q_prod=q_prod-%s WHERE id_prod=%s",(l['qty'],l['id']))
        cur.execute("SELECT COALESCE(MAX(num_fact),0)+1 AS nxt FROM factures")
        num_fact = cur.fetchone()['nxt']
        cur.execute("INSERT INTO factures (id_v,num_fact,date_fact) VALUES (%s,%s,%s)",(id_v,num_fact,today()))
    return jsonify({'id_v':id_v,'total':round(total_ttc,2)}),201

@app.route('/api/ventes/<int:id_>/details')
def vente_details(id_):
    with db() as (cur,_):
        cur.execute("""SELECT dv.*,p.nom_prod,p.ref_prod FROM details_ventes dv
            LEFT JOIN produit p ON dv.id_prod=p.id_prod WHERE dv.id_v=%s""",(id_,))
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/ventes/<int:id_>/paiement', methods=['PUT'])
def update_vente_paiement(id_):
    d = request.json
    with db() as (cur,_):
        cur.execute("""UPDATE ventes SET moyen_paiement=%s,ref_transaction=%s,operateur_mobile=%s,
            credit_paye=%s,credit_reste=%s WHERE id_v=%s""",
            (d.get('moyen_paiement'),d.get('ref_transaction',''),d.get('operateur_mobile',''),
             sf(d.get('credit_paye')),sf(d.get('credit_reste')),id_))
    return jsonify({'ok':True})

@app.route('/api/ventes/<int:id_>', methods=['DELETE'])
def del_vente(id_):
    with db() as (cur,_):
        cur.execute("SELECT id_prod,quantite FROM details_ventes WHERE id_v=%s",(id_,))
        for r in cur.fetchall(): cur.execute("UPDATE produit SET q_prod=q_prod+%s WHERE id_prod=%s",(r['quantite'],r['id_prod']))
        cur.execute("DELETE FROM ventes WHERE id_v=%s",(id_,))
    return jsonify({'ok':True})

# ACHATS
@app.route('/api/achats', methods=['GET'])
def get_achats():
    with db() as (cur,_):
        cur.execute("SELECT a.*,f.nom_four FROM achats a LEFT JOIN fournisseur f ON a.id_four=f.id_four ORDER BY a.id_achat DESC")
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/achats', methods=['POST'])
def add_achat():
    d = request.json; lignes=d.get('lignes',[]); statut=d.get('statut','recu')
    with db() as (cur,_):
        ids=[l['id_prod'] for l in lignes]
        cur.execute("SELECT id_prod,pa_prod,taux_tva FROM produit WHERE id_prod=ANY(%s)",(ids,))
        prods={r['id_prod']:row2d(r) for r in cur.fetchall()}
        ttva=0.0; lc=[]
        for l in lignes:
            p=prods.get(l['id_prod'])
            if not p: continue
            qty=si(l.get('quantite',1)); pu=sf(l.get('pu',p['pa_prod'])); tva=sf(p['taux_tva'])
            ttva+=pu*qty*tva/100; lc.append({'id':l['id_prod'],'qty':qty,'pu':pu})
        cur.execute("INSERT INTO achats (id_four,date_achat,total_tva,statut) VALUES (%s,%s,%s,%s) RETURNING id_achat",
            (d.get('id_four'),today(),round(ttva,2),statut))
        id_a=cur.fetchone()['id_achat']
        for l in lc:
            cur.execute("INSERT INTO details_achats (id_achat,id_prod,quantite,pu_d_a) VALUES (%s,%s,%s,%s)",(id_a,l['id'],l['qty'],l['pu']))
            if statut=='recu': cur.execute("UPDATE produit SET q_prod=q_prod+%s WHERE id_prod=%s",(l['qty'],l['id']))
    return jsonify({'id_achat':id_a}),201

@app.route('/api/achats/<int:id_>/details')
def achat_details(id_):
    with db() as (cur,_):
        cur.execute("SELECT da.*,p.nom_prod,p.ref_prod FROM details_achats da LEFT JOIN produit p ON da.id_prod=p.id_prod WHERE da.id_achat=%s",(id_,))
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/achats/<int:id_>', methods=['DELETE'])
def del_achat(id_):
    with db() as (cur,_):
        cur.execute("SELECT statut FROM achats WHERE id_achat=%s",(id_,))
        row=cur.fetchone()
        if row and row['statut']=='recu':
            cur.execute("SELECT id_prod,quantite FROM details_achats WHERE id_achat=%s",(id_,))
            for r in cur.fetchall(): cur.execute("UPDATE produit SET q_prod=q_prod-%s WHERE id_prod=%s",(r['quantite'],r['id_prod']))
        cur.execute("DELETE FROM achats WHERE id_achat=%s",(id_,))
    return jsonify({'ok':True})

# FACTURES
@app.route('/api/factures')
def get_factures():
    with db() as (cur,_):
        cur.execute("""SELECT f.id_fact,f.num_fact,f.date_fact,f.id_v,v.total_v,v.moyen_paiement,
            CONCAT(c.nom_clt,' ',COALESCE(c.prenom_clt,'')) AS client_nom,
            (SELECT COUNT(*) FROM details_ventes dv WHERE dv.id_v=v.id_v) AS nbr_art_a,
            (SELECT COALESCE(SUM(dv.pu*dv.quantite*dv.taux_tva/100),0) FROM details_ventes dv WHERE dv.id_v=v.id_v) AS tva
            FROM factures f JOIN ventes v ON f.id_v=v.id_v LEFT JOIN client c ON v.id_clt=c.id_clt
            ORDER BY f.id_fact DESC""")
        return jsonify(rows2l(cur.fetchall()))

# CREDITS
@app.route('/api/credits/<int:id_v>/paiements', methods=['GET'])
def get_paiements(id_v):
    with db() as (cur,_):
        cur.execute("SELECT * FROM paiements_credit WHERE id_v=%s ORDER BY id_paiement",(id_v,))
        return jsonify(rows2l(cur.fetchall()))

@app.route('/api/credits/<int:id_v>/paiements', methods=['POST'])
def add_paiement(id_v):
    d=request.json; montant=sf(d.get('montant',0))
    if montant<=0: return jsonify({'error':'Montant invalide'}),400
    with db() as (cur,_):
        cur.execute("SELECT credit_reste,credit_paye FROM ventes WHERE id_v=%s",(id_v,))
        row=cur.fetchone()
        if not row: return jsonify({'error':'Vente introuvable'}),404
        reste=float(row['credit_reste']); old_paye=float(row['credit_paye'])
        if montant>reste+0.01: return jsonify({'error':f'Dépasse le reste dû ({reste:.0f} FCFA)'}),400
        cur.execute("INSERT INTO paiements_credit (id_v,montant,date_paiement,note) VALUES (%s,%s,%s,%s)",
            (id_v,montant,today(),d.get('note','')))
        new_paye=round(old_paye+montant,2); new_reste=max(0.0,round(reste-montant,2))
        cur.execute("UPDATE ventes SET credit_paye=%s,credit_reste=%s WHERE id_v=%s",(new_paye,new_reste,id_v))
    return jsonify({'credit_paye':new_paye,'credit_reste':new_reste})

@app.route('/api/credits/<int:id_v>/paiements/<int:id_p>', methods=['DELETE'])
def del_paiement(id_v,id_p):
    with db() as (cur,_):
        cur.execute("SELECT montant FROM paiements_credit WHERE id_paiement=%s AND id_v=%s",(id_p,id_v))
        row=cur.fetchone()
        if not row: return jsonify({'error':'Paiement introuvable'}),404
        montant=float(row['montant'])
        cur.execute("DELETE FROM paiements_credit WHERE id_paiement=%s",(id_p,))
        cur.execute("SELECT credit_paye,credit_reste,total_v FROM ventes WHERE id_v=%s",(id_v,))
        v=row2d(cur.fetchone())
        new_paye=max(0.0,round(float(v['credit_paye'])-montant,2))
        new_reste=min(float(v['total_v']),round(float(v['credit_reste'])+montant,2))
        cur.execute("UPDATE ventes SET credit_paye=%s,credit_reste=%s WHERE id_v=%s",(new_paye,new_reste,id_v))
    return jsonify({'credit_paye':new_paye,'credit_reste':new_reste})

if __name__ == '__main__':
    if DATABASE_URL:
        init_db()
    else:
        print("DATABASE_URL non defini.")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    if DATABASE_URL:
        try: init_db()
        except Exception as e: print(f"init_db error: {e}")
