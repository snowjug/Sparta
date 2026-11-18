// Private networking: one virtual network with a delegated subnet for the Container Apps environment, a delegated subnet
// for PostgreSQL Flexible Server, and a subnet for private endpoints (Azure Managed Redis), plus the private DNS zones
// that make the private endpoints resolvable inside the network. Deployed only when privateNetworking = true.

param location string
param tags object
param vnetName string

@description('Address space of the virtual network. The Container Apps subnet needs at least a /23 when the environment is Consumption only.')
param vnetAddressPrefix string = '10.40.0.0/16'
param acaSubnetPrefix string = '10.40.0.0/23'
param postgresSubnetPrefix string = '10.40.2.0/24'
param endpointsSubnetPrefix string = '10.40.3.0/24'

@description('Private DNS zone for PostgreSQL Flexible Server. It must end with .postgres.database.azure.com.')
param postgresDnsZoneName string

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: 'aca'
        properties: {
          addressPrefix: acaSubnetPrefix
          delegations: [
            {
              name: 'container-apps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'postgres'
        properties: {
          addressPrefix: postgresSubnetPrefix
          delegations: [
            {
              name: 'postgres-flexible-server'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
        }
      }
      {
        name: 'endpoints'
        properties: {
          addressPrefix: endpointsSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource postgresZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: postgresDnsZoneName
  location: 'global'
  tags: tags
}

resource postgresZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: postgresZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource redisZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.redis.azure.net'
  location: 'global'
  tags: tags
}

resource redisZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: redisZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

output vnetId string = vnet.id
output acaSubnetId string = '${vnet.id}/subnets/aca'
output postgresSubnetId string = '${vnet.id}/subnets/postgres'
output endpointsSubnetId string = '${vnet.id}/subnets/endpoints'
output postgresDnsZoneId string = postgresZone.id
output redisDnsZoneId string = redisZone.id
