"""Parser layer: DDL string -> Schema model.

Uses sqlglot, which supports ClickHouse plus many other dialects. To add a new
database, callers just pass a different `dialect` string -- no code change needed
for the common cases.
"""
from __future__ import annotations
import sqlglot
from sqlglot import exp
from .model import Schema, Table, Column, ForeignKey


# Map sqlglot/raw type tokens to a small normalized vocabulary used by checks.
def _normalize_type(raw: str) -> str:
    r = raw.lower()
    if any(k in r for k in ("int", "uint")):
        return "int"
    if any(k in r for k in ("decimal", "numeric")):
        return "decimal"
    if any(k in r for k in ("float", "double", "real")):
        return "float"
    if "datetime" in r or "timestamp" in r:
        return "datetime"
    if "date" in r:
        return "date"
    if "bool" in r:
        return "bool"
    if any(k in r for k in ("string", "char", "text", "fixedstring", "uuid", "enum")):
        return "string"
    if "array" in r:
        return "array"
    if "map" in r:
        return "map"
    return "other"


def parse_ddl(ddl: str, dialect: str = "clickhouse",
              sample_data: dict | None = None, context: str = "",
              business_keys: dict[str, list[str]] | None = None) -> Schema:
    schema = Schema(dialect=dialect, sample_data=sample_data or {}, context=context)
    business_keys = business_keys or {}
    statements = sqlglot.parse(ddl, read=dialect)

    for stmt in statements:
        if not isinstance(stmt, exp.Create):
            continue
        if (stmt.kind or "").upper() != "TABLE":
            continue

        tbl_name = stmt.this.this.name if isinstance(stmt.this, exp.Schema) else stmt.this.name
        table = Table(name=tbl_name)

        # engine / order by from ClickHouse properties
        props = stmt.args.get("properties")
        if props:
            for p in props.expressions:
                if isinstance(p, exp.EngineProperty):
                    table.engine = p.this.sql(dialect=dialect)
                if isinstance(p, exp.Order):
                    table.sorting_key = [c.name for c in p.find_all(exp.Column)]
                if isinstance(p, exp.PrimaryKey):
                    table.primary_key = ([c.name for c in p.find_all(exp.Column)] or
                                         [e.name for e in p.expressions])

        schema_node = stmt.this if isinstance(stmt.this, exp.Schema) else None
        if schema_node:
            for d in schema_node.expressions:
                if isinstance(d, exp.ColumnDef):
                    raw_type = d.args.get("kind").sql(dialect=dialect) if d.args.get("kind") else ""
                    nullable = "nullable" in raw_type.lower()
                    comment = None
                    default = None
                    is_primary = False
                    for c in d.constraints:
                        ck = c.kind
                        if isinstance(ck, exp.CommentColumnConstraint):
                            comment = ck.this.name if hasattr(ck.this, "name") else str(ck.this)
                        if isinstance(ck, exp.DefaultColumnConstraint):
                            default = ck.this.sql(dialect=dialect)
                        if isinstance(ck, exp.PrimaryKeyColumnConstraint):
                            is_primary = True
                    table.columns.append(Column(
                        name=d.this.name,
                        raw_type=raw_type,
                        base_type=_normalize_type(raw_type),
                        nullable=nullable,
                        default=default,
                        comment=comment,
                    ))
                    if is_primary:
                        table.primary_key.append(d.this.name)
                elif isinstance(d, exp.PrimaryKey):
                    table.primary_key = [c.name for c in d.find_all(exp.Column)] or \
                                        [e.name for e in d.expressions]
                elif isinstance(d, exp.ForeignKey):
                    cols = [c.name for c in d.expressions]
                    ref = d.args.get("reference")
                    if ref:
                        ref_tbl = ref.this.this.name if isinstance(ref.this, exp.Schema) else ref.this.name
                        ref_cols = [c.name for c in ref.find_all(exp.Column)]
                        table.foreign_keys.append(ForeignKey(cols, ref_tbl, ref_cols))

        # Business identity must be declared in context/case metadata. Neither
        # ClickHouse ORDER BY nor PRIMARY KEY guarantees business uniqueness.
        declared_business_key = business_keys.get(table.name)
        if isinstance(declared_business_key, list):
            table.business_key = [str(k) for k in declared_business_key]
            table.business_key_source = "explicit_metadata"
        schema.tables.append(table)

    return schema
