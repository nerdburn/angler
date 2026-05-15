import os
import sqlite3
from datetime import datetime
from .base import Source, Document


class SQLiteSource(Source):
    """Index rows from SQLite tables as searchable documents."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.db_path = os.path.expanduser(
            config.get("db_path", os.environ.get("SQLITE_DB_PATH", ""))
        )
        if not self.db_path:
            raise ValueError("SQLite source requires db_path or SQLITE_DB_PATH env var")

        self.tables = config.get("tables", [])
        if not self.tables:
            raise ValueError("SQLite source requires at least one table in 'tables' config")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_documents(self, since: datetime | None = None) -> list[Document]:
        conn = self._connect()
        documents = []

        try:
            for table_config in self.tables:
                table = table_config["table"]
                text_columns = table_config["text_columns"]
                id_column = table_config.get("id_column", "rowid")
                updated_column = table_config.get("updated_column")

                cols = [id_column] + text_columns
                if updated_column and updated_column not in cols:
                    cols.append(updated_column)

                query = f"SELECT {', '.join(cols)} FROM {table}"
                params = []

                if since and updated_column:
                    query += f" WHERE {updated_column} > ?"
                    params.append(since.isoformat())

                for row in conn.execute(query, params):
                    row_id = row[id_column]

                    # Build document text from text columns
                    parts = []
                    for col in text_columns:
                        value = row[col]
                        if value:
                            parts.append(f"{col}: {value}")

                    content = "\n".join(parts)
                    if not content.strip():
                        continue

                    documents.append(Document(
                        id=f"sqlite://{table}/{row_id}",
                        content=content,
                        metadata={
                            "source": "sqlite",
                            "table": table,
                            "row_id": str(row_id),
                            "db_path": self.db_path,
                        },
                    ))
        finally:
            conn.close()

        return documents
