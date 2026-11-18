// PostgreSQL Flexible Server (version 16) with one database for Sparta. TLS is required (the service default) and the
// connection string is written straight into Key Vault as the secret "sparta-database-url" (never an output).
//
// privateNetworking = true  -> the server lives in a delegated subnet, has no public endpoint, and is reachable only from
//                              inside the virtual network (the Container Apps environment).
// privateNetworking = false -> the server has a public endpoint protected by TLS, a password, and a firewall that allows
//                              Azure-hosted clients (0.0.0.0) plus any extra IPs. That "allow Azure services" rule admits
//                              every Azure customer's workloads to the network layer: use it only for test environments.

param location string
param tags object
param serverName string
param vaultName string

@description('Administrator login. The application connects with it; create a dedicated least-privilege role after the first deployment (docs/DEPLOYMENT.md, Hardening).')
param administratorLogin string = 'spartaadmin'

@secure()
param administratorPassword string

param databaseName string = 'sparta'

@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param tier string = 'Burstable'
param skuName string = 'Standard_B1ms'
param storageSizeGb int = 32
param backupRetentionDays int = 7
param geoRedundantBackup bool = false

@description('Zone-redundant high availability (needs the GeneralPurpose or MemoryOptimized tier in a region with availability zones).')
param highAvailability bool = false

param privateNetworking bool = true
param delegatedSubnetId string = ''
param privateDnsZoneId string = ''

@description('Extra public IPv4 addresses allowed through the firewall (public mode only).')
param allowedPublicIps array = []

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: vaultName
}

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: tier
  }
  properties: {
    version: '16'
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    createMode: 'Default'
    storage: {
      storageSizeGB: storageSizeGb
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    highAvailability: {
      mode: highAvailability ? 'ZoneRedundant' : 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    network: privateNetworking
      ? {
          publicNetworkAccess: 'Disabled'
          delegatedSubnetResourceId: delegatedSubnetId
          privateDnsZoneArmResourceId: privateDnsZoneId
        }
      : {
          publicNetworkAccess: 'Enabled'
        }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!privateNetworking) {
  parent: server
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

@batchSize(1)
resource extraIps 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = [
  for (ip, index) in (privateNetworking ? [] : allowedPublicIps): {
    parent: server
    name: 'allow-${index}'
    properties: {
      startIpAddress: ip
      endIpAddress: ip
    }
    dependsOn: [
      allowAzure
    ]
  }
]

// postgresql+asyncpg://<user>:<url-encoded password>@<fqdn>:5432/<db>?ssl=require
resource databaseUrlSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: vault
  name: 'sparta-database-url'
  properties: {
    value: 'postgresql+asyncpg://${administratorLogin}:${uriComponent(administratorPassword)}@${server.properties.fullyQualifiedDomainName}:5432/${databaseName}?ssl=require'
    contentType: 'SQLAlchemy URL for the Sparta database'
  }
  dependsOn: [
    database
  ]
}

output serverName string = server.name
output serverId string = server.id
output fullyQualifiedDomainName string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
