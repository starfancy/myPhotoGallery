/// <reference types="vite/client" />
declare module "*.vue" {
  import { DefineComponent } from "vue"
  const c: DefineComponent<{}, {}, any>
  export default c
}
