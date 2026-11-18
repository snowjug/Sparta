// Read access to individual Key Vault secrets: one "Key Vault Secrets User" role assignment per secret, scoped to that secret,
// instead of one assignment on the whole vault. The identity can read exactly the secrets named here and nothing else in the
// vault, so a secret that is added to the vault later (or one that belongs to another workload) is not readable by default.
//
// The secrets must already exist when this module runs, because the role assignment is scoped to them: main.bicep makes it
// depend on every module that writes a secret. Role assignments need a few seconds to take effect, so the first
// deployment can fail with "forbidden" when Container Apps resolves a Key Vault reference; deploying again fixes it
// (docs/DEPLOYMENT.md, First deployment).

@description('Name of the existing Key Vault.')
param vaultName string

@description('Principal (object) id of the user-assigned managed identity that gets read access.')
param principalId string

@description('Names of the secrets, inside the vault, that the identity may read.')
param secretNames array

// Built-in role "Key Vault Secrets User": read secret values and metadata, no write, no list of other secrets.
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: vaultName
}

resource secrets 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = [
  for secretName in secretNames: {
    parent: vault
    name: secretName
  }
]

resource readers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for i in range(0, length(secretNames)): {
    scope: secrets[i]
    name: guid(secrets[i].id, principalId, keyVaultSecretsUserRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
      principalId: principalId
      principalType: 'ServicePrincipal'
    }
  }
]

output grantedSecretNames array = secretNames
