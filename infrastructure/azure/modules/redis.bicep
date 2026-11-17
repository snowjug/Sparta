// Azure Managed Redis (Microsoft.Cache/redisEnterprise) for shared rate limits, single-use WebSocket tickets, call locks and
// live-event fan-out. It is used instead of "Azure Cache for Redis": creating Basic/Standard/Premium caches has been blocked
// for new customers since 2026-04-01 and the service retires on 2028-09-30 (docs/DEPLOYMENT.md). The API needs Redis 6.2+
// (GETDEL) and a plain, non-cluster-aware client, so the database uses the EnterpriseCluster policy (one endpoint).
// TLS only (rediss://, port 10000). The connection string is written to Key Vault as "sparta-redis-url", never an output.

param location string
param tags object
param redisName string
param vaultName string

@description('Smallest is Balanced_B0. Check that your region offers the SKU.')
param skuName string = 'Balanced_B0'

@description('Replicate the data set to a second node (the service default). Turning it off lowers cost and availability; the data is ephemeral.')
param highAvailability bool = true

param privateNetworking bool = true
param endpointsSubnetId string = ''
param privateDnsZoneId string = ''

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: vaultName
}

resource redis 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: redisName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: privateNetworking ? 'Disabled' : 'Enabled'
    highAvailability: highAvailability ? 'Enabled' : 'Disabled'
  }
}

resource database 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: redis
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    clusteringPolicy: 'EnterpriseCluster'
    evictionPolicy: 'VolatileLRU'
    accessKeysAuthentication: 'Enabled'
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if (privateNetworking) {
  name: 'pe-${redisName}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: endpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'redis'
        properties: {
          privateLinkServiceId: redis.id
          groupIds: [
            'redisEnterprise'
          ]
        }
      }
    ]
  }
  dependsOn: [
    database
  ]
}

resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (privateNetworking) {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'redis'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

// rediss://:<url-encoded access key>@<host>:10000/0
resource redisUrlSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: vault
  name: 'sparta-redis-url'
  properties: {
    value: 'rediss://:${uriComponent(database.listKeys().primaryKey)}@${redis.properties.hostName}:10000/0'
    contentType: 'Redis URL for SPARTA_REDIS_URL'
  }
}

output redisName string = redis.name
output redisId string = redis.id
output hostName string = redis.properties.hostName
