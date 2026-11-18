// Container Apps environment (Log Analytics logs, optional VNet integration), the API app, the web app and a manual
// "migrate" job that runs `python -m sparta migrate` with the same image and settings as the API. Production never
// migrates at startup, so the job is the release step (docs/DEPLOYMENT.md, Migrations).
//
// Every secret is a Key Vault reference resolved with a user-assigned managed identity: no secret value is stored in the
// template, the parameters or the app definition. The api app and the migrate job share one identity that can read exactly
// the secrets they reference; the internet-facing web app needs no secret, so it has NO identity, unless a private-registry
// password is used (then it gets its own identity that can read that one secret only). Probes send the API's own host name
// in the Host header because the API rejects unknown hosts in production (SPARTA_TRUSTED_HOSTS); without it a probe to the
// container IP gets HTTP 400.

param location string
param tags object

param environmentName string
param apiAppName string
param webAppName string
param migrationJobName string
param workspaceName string

@description('Subnet delegated to Microsoft.App/environments. Empty = no VNet integration (public mode).')
param infrastructureSubnetId string = ''

@description('Resource id of the user-assigned managed identity of the api app and the migrate job. It must be allowed to read every Key Vault secret they reference (modules/secretaccess.bicep, called from main.bicep).')
param identityId string

@description('Resource id of the web app\'s own user-assigned identity, which may read only the registry-password secret. Empty = the web app has no managed identity (the default: it needs no secret).')
param webIdentityId string = ''

@description('Key Vault URI including the trailing slash, for example https://kv-example.vault.azure.net/')
param vaultUri string

param apiImage string
param webImage string

@description('Registry host for private images. Leave empty for public images (a public GHCR package needs no credentials).')
param registryServer string = ''
param registryUsername string = ''
param hasRegistryPassword bool = false

param apiCpu string = '0.5'
param apiMemory string = '1Gi'
param apiMinReplicas int = 1
param apiMaxReplicas int = 3
param webCpu string = '0.25'
param webMemory string = '0.5Gi'
param webMinReplicas int = 1
param webMaxReplicas int = 2

// ---- Sparta settings (see .env.example and services/api/src/sparta/config.py)
@minLength(1)
param oidcIssuer string
@minLength(1)
param oidcAudience string
param oidcJwksUrl string = ''
param extraCorsOrigins array = []
param extraTrustedHosts array = []
param simulatorEnabled bool = false
param telephonyProvider string = 'simulator'
param sttProvider string = 'simulator'
param ttsProvider string = 'simulator'
param llmProvider string = 'rules'
param hasSpeechKey bool = false
param speechRegion string = ''
param hasOpenAiKey bool = false
param azureOpenAiEndpoint string = ''
param azureOpenAiDeployment string = ''
param hasAcsConnectionString bool = false
param acsResourceId string = ''
param entraTenantId string = ''
param eventGridAudience string = ''
param telephonyOwnerUserId string = ''
param forwardingNumber string = ''
param otlpEndpoint string = ''
param logLevel string = 'INFO'
param dailyCallCap int = 200
param maxActiveCalls int = 5

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    vnetConfiguration: empty(infrastructureSubnetId)
      ? null
      : {
          infrastructureSubnetId: infrastructureSubnetId
          internal: false
        }
    zoneRedundant: false
  }
}

// The default domain is known as soon as the environment exists, so the apps can name their own public host.
var apiFqdn = '${apiAppName}.${managedEnvironment.properties.defaultDomain}'
var webFqdn = '${webAppName}.${managedEnvironment.properties.defaultDomain}'

// Key Vault references of the api app and the migrate job. KEEP THIS LIST IN STEP with apiVaultSecretNames in main.bicep: that
// list decides which secrets their identity may read (one role assignment per secret), so a secret referenced here but not
// listed there fails the deployment with "forbidden".
var baseSecrets = [
  {
    name: 'data-keys'
    keyVaultUrl: '${vaultUri}secrets/sparta-data-keys'
    identity: identityId
  }
  {
    name: 'pepper'
    keyVaultUrl: '${vaultUri}secrets/sparta-pepper'
    identity: identityId
  }
  {
    name: 'webhook-secret'
    keyVaultUrl: '${vaultUri}secrets/sparta-webhook-secret'
    identity: identityId
  }
  {
    name: 'database-url'
    keyVaultUrl: '${vaultUri}secrets/sparta-database-url'
    identity: identityId
  }
  {
    name: 'redis-url'
    keyVaultUrl: '${vaultUri}secrets/sparta-redis-url'
    identity: identityId
  }
]

var optionalSecrets = concat(
  hasSpeechKey
    ? [
        {
          name: 'speech-key'
          keyVaultUrl: '${vaultUri}secrets/sparta-speech-key'
          identity: identityId
        }
      ]
    : [],
  hasOpenAiKey
    ? [
        {
          name: 'openai-key'
          keyVaultUrl: '${vaultUri}secrets/sparta-openai-key'
          identity: identityId
        }
      ]
    : [],
  hasAcsConnectionString
    ? [
        {
          name: 'acs-connection-string'
          keyVaultUrl: '${vaultUri}secrets/sparta-acs-connection-string'
          identity: identityId
        }
      ]
    : [],
  hasRegistryPassword
    ? [
        {
          name: 'registry-password'
          keyVaultUrl: '${vaultUri}secrets/sparta-registry-password'
          identity: identityId
        }
      ]
    : []
)

var secrets = concat(baseSecrets, optionalSecrets)

var registries = empty(registryServer)
  ? []
  : [
      {
        server: registryServer
        username: registryUsername
        passwordSecretRef: 'registry-password'
      }
    ]

var baseEnv = [
  { name: 'SPARTA_ENV', value: 'production' }
  { name: 'SPARTA_LOG_JSON', value: 'true' }
  { name: 'SPARTA_LOG_LEVEL', value: logLevel }
  { name: 'SPARTA_AUTH_MODE', value: 'oidc' }
  { name: 'SPARTA_OIDC_ISSUER', value: oidcIssuer }
  { name: 'SPARTA_OIDC_AUDIENCE', value: oidcAudience }
  { name: 'SPARTA_DATA_KEYS', secretRef: 'data-keys' }
  { name: 'SPARTA_PEPPER', secretRef: 'pepper' }
  { name: 'SPARTA_WEBHOOK_SECRET', secretRef: 'webhook-secret' }
  { name: 'SPARTA_DATABASE_URL', secretRef: 'database-url' }
  { name: 'SPARTA_REDIS_URL', secretRef: 'redis-url' }
  { name: 'SPARTA_CORS_ORIGINS', value: join(concat(['https://${webFqdn}'], extraCorsOrigins), ',') }
  { name: 'SPARTA_TRUSTED_HOSTS', value: join(concat([apiFqdn], extraTrustedHosts), ',') }
  { name: 'SPARTA_PUBLIC_BASE_URL', value: 'https://${apiFqdn}' }
  { name: 'SPARTA_SIMULATOR_ENABLED', value: string(simulatorEnabled) }
  { name: 'SPARTA_TELEPHONY_PROVIDER', value: telephonyProvider }
  { name: 'SPARTA_STT_PROVIDER', value: sttProvider }
  { name: 'SPARTA_TTS_PROVIDER', value: ttsProvider }
  { name: 'SPARTA_LLM_PROVIDER', value: llmProvider }
  { name: 'SPARTA_DAILY_CALL_CAP', value: string(dailyCallCap) }
  { name: 'SPARTA_MAX_ACTIVE_CALLS', value: string(maxActiveCalls) }
]

var optionalEnv = concat(
  empty(oidcJwksUrl) ? [] : [{ name: 'SPARTA_OIDC_JWKS_URL', value: oidcJwksUrl }],
  hasSpeechKey
    ? [
        { name: 'SPARTA_AZURE_SPEECH_KEY', secretRef: 'speech-key' }
        { name: 'SPARTA_AZURE_SPEECH_REGION', value: speechRegion }
      ]
    : [],
  hasOpenAiKey
    ? [
        { name: 'SPARTA_AZURE_OPENAI_KEY', secretRef: 'openai-key' }
        { name: 'SPARTA_AZURE_OPENAI_ENDPOINT', value: azureOpenAiEndpoint }
        { name: 'SPARTA_AZURE_OPENAI_DEPLOYMENT', value: azureOpenAiDeployment }
      ]
    : [],
  hasAcsConnectionString
    ? [
        { name: 'SPARTA_ACS_CONNECTION_STRING', secretRef: 'acs-connection-string' }
        { name: 'SPARTA_ACS_CALLBACK_BASE_URL', value: 'https://${apiFqdn}' }
        { name: 'SPARTA_ACS_RESOURCE_ID', value: acsResourceId }
      ]
    : [],
  empty(entraTenantId) ? [] : [{ name: 'SPARTA_ENTRA_TENANT_ID', value: entraTenantId }],
  empty(eventGridAudience) ? [] : [{ name: 'SPARTA_EVENT_GRID_AUDIENCE', value: eventGridAudience }],
  empty(telephonyOwnerUserId) ? [] : [{ name: 'SPARTA_TELEPHONY_OWNER_USER_ID', value: telephonyOwnerUserId }],
  empty(forwardingNumber) ? [] : [{ name: 'SPARTA_FORWARDING_NUMBER', value: forwardingNumber }],
  empty(otlpEndpoint) ? [] : [{ name: 'SPARTA_OTLP_ENDPOINT', value: otlpEndpoint }]
)

var apiEnv = concat(baseEnv, optionalEnv)

var apiProbes = [
  {
    type: 'Startup'
    httpGet: {
      path: '/healthz'
      port: 8000
      httpHeaders: [
        { name: 'Host', value: apiFqdn }
      ]
    }
    initialDelaySeconds: 5
    periodSeconds: 5
    timeoutSeconds: 3
    failureThreshold: 24
  }
  {
    type: 'Liveness'
    httpGet: {
      path: '/healthz'
      port: 8000
      httpHeaders: [
        { name: 'Host', value: apiFqdn }
      ]
    }
    periodSeconds: 20
    timeoutSeconds: 5
    failureThreshold: 3
  }
  {
    type: 'Readiness'
    httpGet: {
      path: '/readyz'
      port: 8000
      httpHeaders: [
        { name: 'Host', value: apiFqdn }
      ]
    }
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3
  }
]

resource apiApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: apiAppName
  location: location
  tags: union(tags, { 'sparta-component': 'api' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: secrets
      registries: registries
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      terminationGracePeriodSeconds: 60
      containers: [
        {
          name: 'api'
          image: apiImage
          command: [
            'python'
            '-m'
            'sparta'
          ]
          // The only network path into the container is the environment's ingress proxy, which sets X-Forwarded-*.
          args: [
            'serve'
            '--host'
            '0.0.0.0'
            '--port'
            '8000'
            '--proxy-headers'
            '--forwarded-allow-ips'
            '*'
          ]
          env: apiEnv
          resources: {
            cpu: json(apiCpu)
            memory: apiMemory
          }
          probes: apiProbes
        }
      ]
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: apiMaxReplicas
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

resource webApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: webAppName
  location: location
  tags: union(tags, { 'sparta-component': 'web' })
  // Internet-facing and secret-free: no managed identity, so it cannot reach Key Vault at all. Only a private-registry
  // password (a Key Vault reference) needs one, and that identity can read nothing else.
  identity: empty(webIdentityId)
    ? {
        type: 'None'
      }
    : {
        type: 'UserAssigned'
        userAssignedIdentities: {
          '${webIdentityId}': {}
        }
      }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: hasRegistryPassword
        ? [
            {
              name: 'registry-password'
              keyVaultUrl: '${vaultUri}secrets/sparta-registry-password'
              identity: webIdentityId
            }
          ]
        : []
      registries: registries
      ingress: {
        external: true
        targetPort: 3000
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          env: [
            { name: 'PORT', value: '3000' }
            { name: 'HOSTNAME', value: '0.0.0.0' }
            { name: 'NODE_ENV', value: 'production' }
          ]
          resources: {
            cpu: json(webCpu)
            memory: webMemory
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/'
                port: 3000
              }
              initialDelaySeconds: 10
              periodSeconds: 20
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/'
                port: 3000
              }
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: webMinReplicas
        maxReplicas: webMaxReplicas
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '100'
              }
            }
          }
        ]
      }
    }
  }
}

resource migrationJob 'Microsoft.App/jobs@2025-01-01' = {
  name: migrationJobName
  location: location
  tags: union(tags, { 'sparta-component': 'migrate' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: secrets
      registries: registries
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: apiImage
          command: [
            'python'
            '-m'
            'sparta'
          ]
          args: [
            'migrate'
          ]
          env: apiEnv
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
    }
  }
}

output environmentId string = managedEnvironment.id
output environmentDefaultDomain string = managedEnvironment.properties.defaultDomain
output apiAppName string = apiApp.name
output apiAppId string = apiApp.id
output apiFqdn string = apiFqdn
output webAppName string = webApp.name
output webFqdn string = webFqdn
output migrationJobName string = migrationJob.name
