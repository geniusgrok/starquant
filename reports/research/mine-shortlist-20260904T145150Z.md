| hash | sharpe | mdd | expression |
| --- | --- | --- | --- |
| 503368238d55d847 | 1.074 | -0.155 | squash(rangepos(168), 2) |
| e89799cab0dbc5cf | 1.021 | -0.233 | cs_rank(rz(ret(720), 336)) |
| e6bb345cbfbf41dd | 0.907 | -0.197 | squash(0.5*(ret(336) / vol(48)) + 0.5*(ret(720) / vol(48)), 2) |
| 9fd2e600e16c6f9a | 0.829 | -0.337 | cs_rank(rz(ret(168), 336)) |
| 1d952e53df52037f | 0.822 | -0.186 | squash(rangepos(168), 1) |
| 0da2b444b2eb09f5 | 0.795 | -0.194 | squash(((ret(336) / vol(48)) * (vol(168) / vol(400))), 2) |
| 17a040eca3f4435e | 0.793 | -0.201 | squash((ret(336) / vol(400)), 2) |
| 64799469b7bfb8d2 | 0.790 | -0.199 | squash(0.5*(ret(336) / vol(48)) + 0.5*(ret(168) / vol(48)), 2) |
| 690cbb4a10358b9e | 0.785 | -0.197 | squash(((ret(336) / vol(48)) * (vol(168) / vol(720))), 2) |
| 19c0690175208d60 | 0.777 | -0.191 | squash(0.5*(ret(336) / vol(48)) + 0.5*(ret(720) / vol(48)), 1) |
| 00f951c68c4d55fa | 0.775 | -0.203 | cs_rank(z(ret(720), 336)) |
| a742db965f4f2725 | 0.775 | -0.195 | squash((ret(336) / vol(168)), 2) |
| 1d20178532903ab8 | 0.762 | -0.193 | squash((ret(336) / vol(48)), 2) |
| 30087bb26dcb37bc | 0.700 | -0.205 | squash(((ret(336) / vol(48)) * (vol(400) / vol(720))), 2) |
| b2785ede400ca9af | 0.664 | -0.222 | squash(0.5*(ret(720) / vol(48)) + 0.5*(ret(168) / vol(48)), 2) |