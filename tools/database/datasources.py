from .types import DataSourcesList, DataSourceItem
import os
from connectors import CosmosDBClient
from semantic_kernel.skill_definition import sk_function

@sk_function(description="Retrieves a list of all datasources.")
async def get_all_datasources_info() -> DataSourcesList:
    cosmosdb = CosmosDBClient()
    datasources_container = os.environ.get('DATASOURCES_CONTAINER', 'datasources')
    documents = await cosmosdb.list_documents(datasources_container)
    datasources_info = []
    for doc in documents:
        datasource_item = DataSourceItem(
            name=doc.get("id", ""),
            description=doc.get("description", ""),
            type=doc.get("type", "")
        )
        datasources_info.append(datasource_item)
    return DataSourcesList(datasources=datasources_info)
