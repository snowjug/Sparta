// Optional alerts, created when alertEmail is set: server errors, restarts and zero replicas of the API, and PostgreSQL
// CPU and storage. They are starting points: tune thresholds to your traffic (docs/DEPLOYMENT.md, Monitoring).

param tags object
param actionGroupName string
param alertEmail string
param apiAppId string
param postgresServerId string

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: actionGroupName
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'sparta'
    enabled: true
    emailReceivers: [
      {
        name: 'owner'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

resource apiServerErrors 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${actionGroupName}-api-5xx'
  location: 'global'
  tags: tags
  properties: {
    description: 'The API returned more than 5 server errors (HTTP 5xx) in 5 minutes.'
    severity: 2
    enabled: true
    scopes: [
      apiAppId
    ]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'ServerErrors'
          metricNamespace: 'Microsoft.App/containerApps'
          metricName: 'Requests'
          dimensions: [
            {
              name: 'statusCodeCategory'
              operator: 'Include'
              values: [
                '5xx'
              ]
            }
          ]
          operator: 'GreaterThan'
          threshold: 5
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

resource apiRestarts 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${actionGroupName}-api-restarts'
  location: 'global'
  tags: tags
  properties: {
    description: 'API containers restarted more than 3 times in 15 minutes (crash loop, failed probes or a configuration problem).'
    severity: 2
    enabled: true
    scopes: [
      apiAppId
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'Restarts'
          metricNamespace: 'Microsoft.App/containerApps'
          metricName: 'RestartCount'
          operator: 'GreaterThan'
          threshold: 3
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

resource apiNoReplicas 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${actionGroupName}-api-no-replicas'
  location: 'global'
  tags: tags
  properties: {
    description: 'The API has no running replica.'
    severity: 1
    enabled: true
    scopes: [
      apiAppId
    ]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'NoReplicas'
          metricNamespace: 'Microsoft.App/containerApps'
          metricName: 'Replicas'
          operator: 'LessThan'
          threshold: 1
          timeAggregation: 'Minimum'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

resource postgresCpu 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${actionGroupName}-postgres-cpu'
  location: 'global'
  tags: tags
  properties: {
    description: 'PostgreSQL CPU has averaged above 85 percent for 15 minutes.'
    severity: 3
    enabled: true
    scopes: [
      postgresServerId
    ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'Cpu'
          metricNamespace: 'Microsoft.DBforPostgreSQL/flexibleServers'
          metricName: 'cpu_percent'
          operator: 'GreaterThan'
          threshold: 85
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

resource postgresStorage 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${actionGroupName}-postgres-storage'
  location: 'global'
  tags: tags
  properties: {
    description: 'PostgreSQL storage is more than 85 percent full.'
    severity: 2
    enabled: true
    scopes: [
      postgresServerId
    ]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT1H'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'Storage'
          metricNamespace: 'Microsoft.DBforPostgreSQL/flexibleServers'
          metricName: 'storage_percent'
          operator: 'GreaterThan'
          threshold: 85
          timeAggregation: 'Maximum'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

output actionGroupId string = actionGroup.id
