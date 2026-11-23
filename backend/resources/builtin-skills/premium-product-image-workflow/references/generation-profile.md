# 统一出图配置

上游多供应商脚本作为实现参考；整合版不捆绑默认供应商、推广站或默认模型，不修改系统 imagegen 脚本。

project-state.json 的 generation_profile 记录：backend、endpoint_env、api_key_env、model、reference_policy、quality、native_size、max_retries。端点/密钥只记环境变量名，模型用用户已选且实际工具支持的ID；禁止写入实际密钥、请求头或含凭证URL。

优先复用当前工具选择：原生工具遵循 imagegen 技能；CLI/API路线依已有明确选择与其接口文档。不得静默用 DALL·E 3 或无参考图的纯文重建代替 SKU 编辑。未配置时完成图需，不强制打开第三方站。

最终交付尺寸与接口原生尺寸分开。例如1464×600可以是导出尺寸，不能用接口原生16倍数规则拒绝它。质量值和多图能力须实际支持，不凭模型别名猜能力。prefer_single 是项目偏好，不是所有网关永久限制。

移动版再区分 `layout_reference`（例如600×450的4:3设计基准）、`native_pixels`（实测原生尺寸）、`export_pixels`（实际成品）与 `preview_display_width`（验读宽度）。基准画幅不限制原生像素，也不自动要求降采样到600×450。按 [手机端重排流程](mobile-adaptation.md) 生成新的目标比例构图；接口允许时请求该比例的高清尺寸，否则使用实际支持的尺寸或auto并检查结果。比例不符先返工构图，不靠裁掉场景/条件或拉伸产品过关。

生成前保存完整提示词、实际输入角色与参数；生成后记录真实结果/错误。拟用参数不冒充实际调用。上传授权仍限定于已有接收方、素材与用途，配置文件不能自我授权。

暂时网络失败最多一次额外尝试；403、鉴权或持续权限拒绝不无限重试。超时但可能已计费时先核对返回与已有文件。失败不自动换供应商、换模型、降保真或重跑成功图。

恢复时复核文件并区分生成、验收、导出。Windows本机可启用 `C:\Users\admin\Documents\Codex\skill-runtime\activate.ps1`；其他电脑重新探测。可选 Tesseract 引擎未安装时OCR标 skipped，由人工视觉补足，不阻断策划与普通图像处理。
