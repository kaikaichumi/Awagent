from __future__ import annotations

from botocore.exceptions import ClientError

from waagent.scan.collectors.base import Collector


class DynamoDbCollector(Collector):
    """DynamoDB 資料表清單，含 PITR（continuous backups）與 SSE 設定。"""

    service = "dynamodb"

    def collect(self, session, region: str, boto_cfg) -> dict:
        ddb = session.client("dynamodb", region_name=region, config=boto_cfg)
        table_names = self.call(ddb, "list_tables", "TableNames")
        tables: list[dict] = []
        for name in table_names:
            table = self.call(ddb, "describe_table", TableName=name).get("Table", {})
            table["ContinuousBackups"] = self._try(
                ddb, "describe_continuous_backups", TableName=name
            )
            tables.append(table)
        return {"tables": tables}

    def _try(self, client, method: str, **kwargs):
        try:
            return self.call(client, method, **kwargs)
        except ClientError as e:
            return {"_error": e.response.get("Error", {}).get("Code", "")}
