const LAYERS = [
  ['Azure SQL Database', 'Private serverless mtl_retail database (operational store systems, synthetic).'],
  ['Fabric Mirroring', 'Continuous zero-ETL replication through the VNet data gateway into a Mirrored SQL database.'],
  ['Bronze', 'OneLake shortcuts to the mirrored tables — no copies.'],
  ['Silver', 'Cleansed, conformed and deduplicated data with a data-quality event log.'],
  ['Gold', 'Star schema, KPI tables and ML outputs for every consumer.'],
  ['Data Science', 'LightGBM sales forecast and low-stock prediction tracked in MLflow and registered as ML models.'],
  ['Semantic model + report', 'Direct Lake model with governed measures and a green-and-white Power BI report.'],
  ['Fabric IQ ontology', 'Business entities, relationships and EN/FR synonyms over Gold.'],
  ['Data Agent', 'Read-only bilingual advisor grounded on the ontology, embedded here through a server function.'],
  ['Fabric App', 'This app: Rayfin front end, Fabric SQL database for reorder requests, closed loop back to Bronze.'],
];

export function About() {
  return (
    <div className="about-grid">
      <section className="panel">
        <span className="eyebrow dark">HOW FABRIC POWERS THIS APP</span>
        <h2>From store systems to decisions on one platform</h2>
        <ol className="architecture">{LAYERS.map(([name, text]) => <li key={name}><b>{name}</b><span>{text}</span></li>)}</ol>
      </section>
      <section className="panel boundary-list">
        <h2>Responsible demo boundaries</h2>
        <p><b>Synthetic data.</b> Stores use Quebec city names for realism; every product, brand, supplier and figure is fabricated and illustrative — not Maison MTL data.</p>
        <p><b>Human approval.</b> The advisor is read-only. Reorder requests are review records; a buyer approves before any transfer or purchase order.</p>
        <p><b>No token in the browser.</b> Advisor questions run in a Fabric User Data Function using the signed-in user's Fabric token server-side.</p>
        <p><b>Your requests only.</b> Row-level policies let each employee create and read only their own reorder requests.</p>
      </section>
    </div>
  );
}
