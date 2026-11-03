import { ref } from 'vue'
import { errorText } from '../api.js'

// Request state for one of the professional analyses (engineering, economics, break-even, group):
// the latest response, a loading flag and an error, with older responses discarded when a newer
// request was sent meanwhile. One shared instance per key, as for the other composables.
const instances = {}

export function useAnalysis(key) {
  if (instances[key]) return instances[key]
  const data = ref(null)
  const loading = ref(false)
  const error = ref('')
  let requestId = 0

  async function run(request) {
    const id = ++requestId
    loading.value = true
    try {
      const result = await request()
      if (id === requestId) {
        data.value = result
        error.value = ''
      }
    } catch (e) {
      if (id === requestId) error.value = errorText(e)
    } finally {
      if (id === requestId) loading.value = false
    }
  }

  instances[key] = { data, loading, error, run }
  return instances[key]
}

// The body every analysis shares: the site, its parameters and the design-life study inputs.
export function siteBody(dss) {
  return {
    context: dss.selectedContext.value,
    params: { ...dss.params },
    study: { ...dss.study },
  }
}
