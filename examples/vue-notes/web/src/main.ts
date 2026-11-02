import { createApp } from "vue";

import "./style.css";
import App from "./App.vue";

createApp(App).mount("#app");

// cakeui:bridge: 由 CakeUI 添加；删掉这一行即解除与 CakeUI 的绑定。
import "./lib/cakeui/cakeui-boot";
