module nand_bad(a, b, y);
input a, b;
output reg y;

always @(a or b) begin
  if (a)
    y = ~(a & b);
end

endmodule