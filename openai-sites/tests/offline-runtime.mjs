/** Test-only network boundary. Never imported by the deployed Worker. */
export function denyExternalFetch(){
 throw new Error('External fetch is disabled in synthetic Rumbo tests');
}
export function createOfflineRuntime(Runtime,options){
 if(options.workers||options.fetchMock)throw new Error('Synthetic runtime expects one worker without a separate fetch mock');
 return new Runtime({...options,
  // Explicit false takes precedence over environment/cache settings and skips
  // Miniflare's default https://workers.cloudflare.com/cf.json metadata fetch.
  cf:false,
  telemetry:{enabled:false},
  // Installed Miniflare supports a function as the Worker outbound service.
  // Reject in-process instead of allowing network requests from tested code.
  outboundService:denyExternalFetch,
 });
}
