// Log Analytics workspace (all container and platform logs land here) and a workspace-based Application Insights resource.
// The API writes one redacted JSON log line per event to stdout; Container Apps ships it to ContainerAppConsoleLogs_CL.
// Application Insights is provisioned and linked to the workspace for dashboards and future instrumentation: the API does
// not ship an Azure Monitor exporter yet (it exports OTLP traces to SPARTA_OTLP_ENDPOINT when one is configured).

param location string
param tags object
param workspaceName string
param appInsightsName string

@description('Days to keep logs. 30 is the free retention of the PerGB2018 SKU; raise it only if you need it (cost).')
@minValue(30)
@maxValue(730)
param retentionInDays int = 30

@description('Daily ingestion cap in GB (-1 = no cap). A cap protects the budget but drops logs once reached.')
param dailyQuotaGb int = 1

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    workspaceCapping: {
      dailyQuotaGb: dailyQuotaGb
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
    RetentionInDays: retentionInDays
  }
}

output workspaceName string = workspace.name
output workspaceId string = workspace.id
output appInsightsName string = appInsights.name
output appInsightsId string = appInsights.id
