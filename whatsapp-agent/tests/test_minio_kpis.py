import unittest
from agent.minio_kpis import debug_vendas_hoje


class TestMinioKpis(unittest.TestCase):
    def test_debug_vendas_hoje_structure(self):
        """Verifica que debug_vendas_hoje retorna as chaves esperadas e formatos básicos."""
        out = debug_vendas_hoje()
        self.assertIsInstance(out, dict)
        for key in ["data_referencia", "total_linhas_hoje", "colunas_do_parquet", "datas_distintas_no_arquivo"]:
            self.assertIn(key, out)
        self.assertIsInstance(out["datas_distintas_no_arquivo"], list)
        self.assertIsInstance(out["total_linhas_hoje"], int)
        self.assertTrue(
            all(isinstance(d, str) for d in out["datas_distintas_no_arquivo"]) or len(out["datas_distintas_no_arquivo"]) == 0
        )


if __name__ == "__main__":
    unittest.main()
