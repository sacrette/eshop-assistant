import pathlib

KB_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "kb"


SOURCE_TYPES: dict[str, str] = {
    "product-faq.md": "faq",
    "returns-policy.md": "policy",
    "after-sales-manual.md": "manual",
    "product-specs.md": "spec",
    "member-benefits.md": "policy",
    "billing-shipping.md": "policy",
}


CONTENT_TYPES: tuple[str, ...] = ("faq", "policy", "manual", "spec")
CONTENT_TYPE_DESC: dict[str, str] = {
    "faq": "商品 FAQ:questions 填真实问法",
    "policy": "政策条款:questions 填章节标题、category 填上级路径",
    "manual": "售后手册:同政策,按标题层级切",
    "spec": "商品规格:含具体型号,精确词召回靠它",
}
