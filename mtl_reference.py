"""Reference data for the SYNTHETIC Maison MTL demo.

Store names use Quebec cities for realism, but every figure, brand, supplier and product is fictional and illustrative.
"""
from datetime import date

SEED = 20261103
START = date(2024, 11, 4)
END = date(2026, 11, 3)
COLD_SNAP_START = date(2026, 10, 22)
DC_CODE = "DC-QC"

# store_id, code, name, city, region, raw province, format, opened, sqft, lat, lon, traffic index, DC transfer days
STORES = [
    (1, "QC-VQ", "Maison MTL Vieux-Québec", "Québec", "Capitale-Nationale", "QC", "Flagship", 1840, 62000, 46.8123, -71.2079, 1.30, 1),
    (2, "QC-SF", "Maison MTL Sainte-Foy", "Québec", "Capitale-Nationale", "Québec", "Regional mall", 1999, 88000, 46.7712, -71.2861, 1.20, 1),
    (3, "MT-CV", "Maison MTL Montréal Centre-Ville", "Montréal", "Montréal", "QC", "Flagship", 1999, 115000, 45.5030, -73.5720, 1.50, 2),
    (4, "LV-CL", "Maison MTL Laval", "Laval", "Laval", "Quebec", "Regional mall", 2006, 92000, 45.5700, -73.7500, 1.10, 2),
    (5, "BR-RS", "Maison MTL Brossard Rive-Sud", "Brossard", "Montérégie", "QC", "Lifestyle centre", 2009, 80000, 45.4440, -73.4400, 1.00, 2),
    (6, "SB-PR", "Maison MTL St-Bruno", "Saint-Bruno-de-Montarville", "Montérégie", "qc", "Regional mall", 2001, 70000, 45.5180, -73.3600, 0.85, 2),
    (7, "SH-ES", "Maison MTL Sherbrooke", "Sherbrooke", "Estrie", "QC", "Regional mall", 2004, 65000, 45.3800, -71.9300, 0.75, 2),
    (8, "GA-OU", "Maison MTL Gatineau", "Gatineau", "Outaouais", "Québec", "Regional mall", 2005, 68000, 45.4770, -75.7010, 0.80, 3),
    (9, "TR-MA", "Maison MTL Trois-Rivières", "Trois-Rivières", "Mauricie", "QC", "Regional mall", 2008, 60000, 46.3500, -72.5800, 0.70, 2),
    (10, "LE-CA", "Maison MTL Lévis", "Lévis", "Chaudière-Appalaches", "QC", "Lifestyle centre", 2012, 58000, 46.7900, -71.1800, 0.65, 1),
    (11, DC_CODE, "Centre de distribution Québec", "Québec", "Capitale-Nationale", "QC", "Distribution centre", 1995, 450000, 46.8000, -71.3500, 0.0, 0),
]

REGIONS = {
    "Capitale-Nationale": ("Québec City metro", "03"),
    "Montréal": ("Greater Montréal", "06"),
    "Laval": ("Greater Montréal", "13"),
    "Montérégie": ("Greater Montréal", "16"),
    "Estrie": ("Regional Quebec", "05"),
    "Outaouais": ("Regional Quebec", "07"),
    "Mauricie": ("Regional Quebec", "04"),
    "Chaudière-Appalaches": ("Québec City metro", "12"),
}

# supplier_id, code, name, country, lead time days, on-time %
SUPPLIERS = [
    (1, "SUP-ABO", "Atelier Boréal Outerwear Inc.", "Canada", 21, 92.0),
    (2, "SUP-NFC", "Nordik Footwear Co.", "Canada", 28, 85.0),
    (3, "SUP-LKN", "Laurentian Knits Ltd.", "Canada", 14, 95.0),
    (4, "SUP-MTM", "Maison Textile Montréal", "Canada", 10, 96.0),
    (5, "SUP-PLW", "Porto Leather Works", "Portugal", 42, 88.0),
    (6, "SUP-LHG", "Lumière Home Goods", "Canada", 18, 94.0),
    (7, "SUP-CSS", "Coastline Swim Studio", "United States", 30, 90.0),
    (8, "SUP-ATL", "Atlas Apparel Sourcing", "Vietnam", 56, 87.0),
]

# sku, name, department, category, subcategory, brand, supplier, unit cost, price, season profile, base units/day, case
PRODUCTS = [
    ("W-OUT-101", "Women's Long Down Parka", "Women", "Outerwear", "Parkas", "Boréale", "SUP-ABO", 170, 425, "Winter", 1.1, 4),
    ("W-OUT-102", "Women's Wool-Blend Wrap Coat", "Women", "Outerwear", "Wool coats", "Atelier 31", "SUP-MTM", 120, 295, "FallWinter", 0.9, 4),
    ("W-OUT-103", "Women's Packable Light Down Jacket", "Women", "Outerwear", "Light jackets", "Boréale", "SUP-ATL", 55, 139, "Shoulder", 1.0, 6),
    ("W-OUT-104", "Women's Classic Trench Coat", "Women", "Outerwear", "Trench coats", "Atelier 31", "SUP-ATL", 70, 189, "Spring", 0.7, 4),
    ("W-KNT-201", "Women's Merino Crewneck Sweater", "Women", "Knitwear", "Sweaters", "Atelier 31", "SUP-LKN", 28, 79, "FallWinter", 2.2, 6),
    ("W-KNT-202", "Women's Cashmere Turtleneck", "Women", "Knitwear", "Sweaters", "Atelier 31", "SUP-LKN", 75, 189, "FallWinter", 0.9, 4),
    ("W-KNT-203", "Women's Cotton Cardigan", "Women", "Knitwear", "Cardigans", "Atelier 31", "SUP-MTM", 22, 59, "Core", 1.4, 6),
    ("W-DRS-301", "Women's Linen Midi Dress", "Women", "Dresses", "Day dresses", "Atelier 31", "SUP-MTM", 34, 98, "Summer", 1.3, 6),
    ("W-DRS-302", "Women's Knit Sweater Dress", "Women", "Dresses", "Knit dresses", "Atelier 31", "SUP-LKN", 38, 109, "FallWinter", 0.9, 6),
    ("W-DRS-303", "Women's Satin Holiday Dress", "Women", "Dresses", "Occasion dresses", "Atelier 31", "SUP-ATL", 45, 139, "Holiday", 0.7, 4),
    ("W-DNM-401", "Women's High-Rise Straight Jean", "Women", "Denim", "Jeans", "Twill & Co.", "SUP-ATL", 26, 79, "BackToSchool", 2.4, 12),
    ("W-DNM-402", "Women's Wide-Leg Jean", "Women", "Denim", "Jeans", "Twill & Co.", "SUP-ATL", 28, 89, "Core", 1.6, 12),
    ("W-SWM-501", "Women's One-Piece Swimsuit", "Women", "Swimwear", "Swimsuits", "Rivage", "SUP-CSS", 25, 79, "Summer", 1.2, 6),
    ("W-SWM-502", "Women's Bikini Set", "Women", "Swimwear", "Swimsuits", "Rivage", "SUP-CSS", 22, 69, "Summer", 1.1, 6),
    ("W-FTW-601", "Women's Waterproof Winter Boot", "Women", "Footwear", "Winter boots", "Nordik", "SUP-NFC", 78, 195, "Winter", 1.0, 6),
    ("W-FTW-602", "Women's Leather Ankle Boot", "Women", "Footwear", "Boots", "Atelier 31", "SUP-PLW", 70, 179, "FallWinter", 0.8, 6),
    ("W-FTW-603", "Women's Leather Sandal", "Women", "Footwear", "Sandals", "Atelier 31", "SUP-PLW", 30, 89, "Summer", 1.0, 6),
    ("M-OUT-101", "Men's Expedition Down Parka", "Men", "Outerwear", "Parkas", "Boréale", "SUP-ABO", 190, 475, "Winter", 0.9, 4),
    ("M-OUT-102", "Men's Wool Topcoat", "Men", "Outerwear", "Wool coats", "Ligne Urbaine", "SUP-MTM", 130, 320, "FallWinter", 0.6, 4),
    ("M-OUT-103", "Men's Quilted Vest", "Men", "Outerwear", "Light jackets", "Ligne Urbaine", "SUP-ATL", 35, 99, "Shoulder", 0.8, 6),
    ("M-KNT-201", "Men's Merino Quarter-Zip", "Men", "Knitwear", "Sweaters", "Ligne Urbaine", "SUP-LKN", 30, 85, "FallWinter", 1.6, 6),
    ("M-KNT-202", "Men's Fisherman Cable Sweater", "Men", "Knitwear", "Sweaters", "Ligne Urbaine", "SUP-LKN", 40, 115, "FallWinter", 0.9, 6),
    ("M-SHT-301", "Men's Oxford Button-Down Shirt", "Men", "Shirts", "Dress shirts", "Ligne Urbaine", "SUP-ATL", 20, 65, "Core", 2.0, 12),
    ("M-SHT-302", "Men's Flannel Overshirt", "Men", "Shirts", "Casual shirts", "Ligne Urbaine", "SUP-MTM", 26, 75, "FallWinter", 1.3, 6),
    ("M-SHT-303", "Men's Linen Short-Sleeve Shirt", "Men", "Shirts", "Casual shirts", "Ligne Urbaine", "SUP-MTM", 22, 69, "Summer", 1.1, 6),
    ("M-DNM-401", "Men's Slim Selvedge Jean", "Men", "Denim", "Jeans", "Twill & Co.", "SUP-ATL", 30, 95, "Core", 2.0, 12),
    ("M-DNM-402", "Men's Stretch Chino", "Men", "Denim", "Pants", "Ligne Urbaine", "SUP-ATL", 22, 69, "Core", 1.5, 12),
    ("M-SWM-501", "Men's Swim Trunk", "Men", "Swimwear", "Swim trunks", "Rivage", "SUP-CSS", 18, 55, "Summer", 1.0, 6),
    ("M-FTW-601", "Men's Insulated Winter Boot", "Men", "Footwear", "Winter boots", "Nordik", "SUP-NFC", 84, 210, "Winter", 0.9, 6),
    ("M-FTW-602", "Men's Leather Chelsea Boot", "Men", "Footwear", "Boots", "Ligne Urbaine", "SUP-PLW", 85, 225, "FallWinter", 0.6, 6),
    ("M-FTW-603", "Men's Canvas Sneaker", "Men", "Footwear", "Sneakers", "Twill & Co.", "SUP-ATL", 25, 75, "Summer", 1.2, 12),
    ("K-OUT-101", "Kids' One-Piece Snowsuit", "Kids", "Outerwear", "Snowsuits", "Petits Flocons", "SUP-ABO", 62, 160, "Winter", 0.8, 6),
    ("K-OUT-102", "Kids' Puffer Jacket", "Kids", "Outerwear", "Jackets", "Petits Flocons", "SUP-ATL", 34, 95, "Winter", 1.1, 6),
    ("K-OUT-103", "Kids' Rain Jacket", "Kids", "Outerwear", "Jackets", "Petits Flocons", "SUP-ATL", 18, 49, "Spring", 0.8, 12),
    ("K-KNT-201", "Kids' Fleece Hoodie", "Kids", "Knitwear", "Hoodies", "Petits Flocons", "SUP-MTM", 12, 35, "BackToSchool", 1.6, 12),
    ("K-APP-301", "Kids' Graphic Tee 3-Pack", "Kids", "Apparel", "Tops", "Petits Flocons", "SUP-ATL", 9, 29, "BackToSchool", 2.2, 12),
    ("K-APP-302", "Kids' Jogger Pant", "Kids", "Apparel", "Bottoms", "Petits Flocons", "SUP-ATL", 10, 32, "BackToSchool", 1.8, 12),
    ("K-SWM-501", "Kids' UV Swimsuit", "Kids", "Swimwear", "Swimsuits", "Rivage", "SUP-CSS", 12, 35, "Summer", 0.9, 12),
    ("K-FTW-601", "Kids' Snow Boot", "Kids", "Footwear", "Winter boots", "Nordik", "SUP-NFC", 34, 89, "Winter", 1.0, 6),
    ("K-ACC-701", "Kids' Mitts and Toque Set", "Kids", "Accessories", "Cold-weather accessories", "Petits Flocons", "SUP-LKN", 9, 28, "Winter", 1.5, 12),
    ("H-BED-101", "Flannel Duvet Cover Set", "Home", "Bedding", "Duvet covers", "Maison Laurentienne", "SUP-LHG", 48, 129, "FallWinter", 0.9, 4),
    ("H-BED-102", "Washed Linen Sheet Set", "Home", "Bedding", "Sheets", "Maison Laurentienne", "SUP-LHG", 60, 169, "Core", 0.7, 4),
    ("H-BED-103", "Down-Alternative Duvet", "Home", "Bedding", "Duvets", "Maison Laurentienne", "SUP-LHG", 55, 149, "FallWinter", 0.7, 4),
    ("H-BED-104", "Chunky Knit Throw", "Home", "Bedding", "Throws", "Maison Laurentienne", "SUP-LKN", 26, 79, "Holiday", 1.2, 6),
    ("H-BTH-201", "Waffle Bath Towel", "Home", "Bath", "Towels", "Maison Laurentienne", "SUP-LHG", 12, 35, "Core", 2.0, 12),
    ("H-BTH-202", "Plush Bath Robe", "Home", "Bath", "Robes", "Maison Laurentienne", "SUP-LHG", 32, 89, "Holiday", 0.8, 6),
    ("H-DEC-301", "Balsam Fir Soy Candle", "Home", "Décor", "Candles", "Maison Laurentienne", "SUP-LHG", 10, 34, "Holiday", 2.4, 12),
    ("H-DEC-302", "Ceramic Bud Vase", "Home", "Décor", "Vases", "Maison Laurentienne", "SUP-LHG", 18, 55, "Core", 0.8, 6),
    ("H-DEC-303", "Glass Ornament Set", "Home", "Décor", "Holiday décor", "Maison Laurentienne", "SUP-ATL", 8, 29, "HolidayPeak", 1.8, 12),
    ("H-KIT-401", "Stoneware Dinner Set", "Home", "Kitchen", "Dinnerware", "Maison Laurentienne", "SUP-LHG", 45, 129, "Core", 0.6, 4),
    ("A-CWA-101", "Merino Cable Toque", "Accessories", "Cold-weather accessories", "Toques", "Boréale", "SUP-LKN", 13, 38, "Winter", 3.0, 12),
    ("A-CWA-102", "Shearling-Lined Leather Mitts", "Accessories", "Cold-weather accessories", "Mitts", "Boréale", "SUP-PLW", 24, 65, "Winter", 1.8, 12),
    ("A-CWA-103", "Oversized Wool Scarf", "Accessories", "Cold-weather accessories", "Scarves", "Atelier 31", "SUP-LKN", 18, 55, "Winter", 2.0, 12),
    ("A-CWA-104", "Touchscreen Knit Gloves", "Accessories", "Cold-weather accessories", "Gloves", "Boréale", "SUP-LKN", 8, 25, "Winter", 2.2, 12),
    ("A-BAG-201", "Leather Tote Bag", "Accessories", "Bags", "Totes", "Atelier 31", "SUP-PLW", 75, 198, "Holiday", 0.7, 4),
    ("A-BAG-202", "Nylon Crossbody Bag", "Accessories", "Bags", "Crossbody", "Ligne Urbaine", "SUP-ATL", 22, 65, "Core", 1.1, 6),
    ("A-SUN-301", "Polarized Sunglasses", "Accessories", "Sun accessories", "Sunglasses", "Rivage", "SUP-CSS", 20, 75, "Summer", 1.2, 12),
    ("A-SUN-302", "Straw Sun Hat", "Accessories", "Sun accessories", "Hats", "Rivage", "SUP-CSS", 12, 39, "Summer", 1.0, 12),
    ("A-JWL-401", "Gold Hoop Earrings", "Accessories", "Jewellery", "Earrings", "Atelier 31", "SUP-ATL", 10, 39, "Holiday", 1.5, 12),
    ("A-JWL-402", "Pendant Necklace", "Accessories", "Jewellery", "Necklaces", "Atelier 31", "SUP-ATL", 12, 45, "Holiday", 1.1, 12),
]

BRANDS = {
    "Boréale": "Technical outerwear and cold-weather essentials",
    "Atelier 31": "Contemporary women's and accessories label",
    "Ligne Urbaine": "Modern menswear",
    "Twill & Co.": "Denim and casual basics",
    "Rivage": "Swim and sun",
    "Nordik": "Winter footwear",
    "Petits Flocons": "Kids' apparel and outerwear",
    "Maison Laurentienne": "Home, bed and bath",
}

# Monthly seasonal index (Jan..Dec) per profile; interpolated daily between month midpoints.
SEASON = {
    "Winter": [1.5, 0.9, 0.45, 0.2, 0.1, 0.06, 0.06, 0.15, 0.5, 1.3, 2.2, 2.6],
    "FallWinter": [1.0, 0.8, 0.6, 0.4, 0.3, 0.25, 0.25, 0.6, 1.2, 1.6, 1.8, 1.9],
    "Summer": [0.15, 0.2, 0.4, 0.8, 1.6, 2.4, 2.4, 1.4, 0.5, 0.2, 0.15, 0.25],
    "Spring": [0.3, 0.5, 1.4, 2.0, 1.8, 0.8, 0.4, 0.4, 0.9, 0.8, 0.4, 0.3],
    "Shoulder": [0.5, 0.6, 1.2, 1.6, 1.3, 0.6, 0.5, 0.7, 1.5, 1.4, 0.9, 0.7],
    "Core": [0.8, 0.85, 0.95, 1.0, 1.0, 0.95, 0.9, 1.0, 1.05, 1.0, 1.1, 1.5],
    "BackToSchool": [0.7, 0.7, 0.8, 0.85, 0.9, 0.85, 0.9, 2.2, 1.8, 0.9, 0.9, 1.2],
    "Holiday": [0.6, 0.7, 0.7, 0.7, 0.75, 0.7, 0.65, 0.7, 0.8, 0.9, 1.6, 3.0],
    "HolidayPeak": [0.25, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.25, 0.3, 0.6, 1.8, 4.0],
}

DOW = [0.82, 0.8, 0.86, 1.0, 1.15, 1.45, 0.92]  # Monday..Sunday
CLOSED = {(1, 1), (6, 24), (7, 1), (12, 25)}
BLACK_FRIDAY = {date(2024, 11, 29), date(2025, 11, 28), date(2026, 11, 27)}
